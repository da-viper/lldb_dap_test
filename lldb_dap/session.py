from __future__ import annotations

import dataclasses
import functools
import io
import itertools
import json
import subprocess
import threading
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, Generic, Optional, Type, TypeVar, Union

from lldb_dap.dap_types import (
    AnyEvent,
    AnyResponse,
    ArgsProtocol,
    Capabilities,
    CapabilitiesEvent,
    ContinueArgs,
    DAPError,
    DisconnectArgs,
    ErrorResponse,
    Event,
    ExitedEvent,
    GotoArgs,
    InitializeArgs,
    InitializedEvent,
    Message,
    MessageType,
    NextArgs,
    OutputCategory,
    OutputEvent,
    RawMessage,
    Request,
    RestartArgs,
    Response,
    ReverseResponse,
    RunInTerminalRequest,
    RunInTerminalResponse,
    StepInArgs,
    StepOutArgs,
    StoppedEvent,
    TerminateArgs,
    dict_to_message,
)
from lldb_dap.utils import (
    DAPConnection,
    DebugAdapter,
    EventHistory,
    MessageHandler,
    redirect_stream,
)

R = TypeVar("R")

# Any Request that resumes execution (or terminates the session),
# invalidates any frameId or variablesReference captured during the current stop.
# Sending one of these Requests advances the session's stop_generation.
# To prevent using a frameId or variablesReference that is no longer valid once
# the session continues.
_RESUMING_COMMANDS = (
    ContinueArgs,
    NextArgs,
    StepInArgs,
    StepOutArgs,
    GotoArgs,
    RestartArgs,
    TerminateArgs,
)


@dataclass(frozen=True)
class ResponseHandle(Generic[AnyResponse]):
    seq: int
    response_class: Type[AnyResponse]

    def __post_init__(self):
        assert issubclass(
            self.response_class, Response
        ), f"'{self.response_class.__name__}' must be a subclass of Response."


def _synchronized(method: Callable[..., R]) -> Callable[..., R]:
    """Class method decorator to acquire and release the lock automatically."""

    @functools.wraps(method)
    def wrapper(self, *args: Any, **kwargs: Any) -> R:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class _DAPSessionState:
    """TODO: explain what this class is used for

    We try to hold less states as possible.
    most information you can get it from the event thread.
    # We explicitly do not want to hold the seen / verified breakpoints
    # as this may change when we get any breakpoint response
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._initialized = False
        self._capabilities = Capabilities()
        self.output_streams = {
            OutputCategory.STDOUT: io.StringIO(),
            OutputCategory.STDERR: io.StringIO(),
            OutputCategory.CONSOLE: io.StringIO(),
            OutputCategory.IMPORTANT: io.StringIO(),
            OutputCategory.TELEMETRY: io.StringIO(),
        }
        # TODO: still debating if we need to store stopped_thread
        # and force all tests to get a stopped thread id.
        self._stopped_thread_id: Optional[int] = None
        self._last_response: Optional[Response] = None
        self._stop_generation: int = 0

    @property
    @_synchronized
    def is_initialized(self):
        return self._initialized

    @_synchronized
    def set_initialized(self, val: bool):
        self._initialized = val

    @property
    @_synchronized
    def stopped_thread_id(self):
        return self._stopped_thread_id

    @_synchronized
    def set_stopped_thread_id(self, id: int):
        assert isinstance(id, int)
        self._stopped_thread_id = id

    @property
    @_synchronized
    def stop_generation(self) -> int:
        """The current stop's generation number.

        Monotonic counter identifying the current session stop.
        Incremented every time we send a request that resumes or terminates execution
        (see `_RESUMING_COMMANDS`).
        """
        return self._stop_generation

    @_synchronized
    def advance_stop_generation(self) -> int:
        self._stop_generation += 1
        return self._stop_generation

    @_synchronized
    def capabilities(self):
        return dataclasses.replace(self._capabilities)

    @_synchronized
    def update_capabilities(self, new_capabilities: Capabilities):
        kwargs = {
            field: value
            for field, value in vars(new_capabilities).items()
            if value is not None
        }
        self._capabilities = dataclasses.replace(self._capabilities, **kwargs)


class Session:

    """DAP TestClient for testing debug adapters"""

    # TODO: change how we think about things
    # The normal session class should only deal with the raw messages.
    # delegate other things to the test session

    def __init__(
        self,
        test_dir: Path,
        adapter: DebugAdapter,
        message_timeout: float,
        log_file: Optional[str] = None,
    ):
        self._test_dir = test_dir
        log_file = log_file or str(self._test_dir / "test_dap.log")
        self._test_message_log = open(log_file, "w")

        self._message_timeout = message_timeout
        self._next_sequence = functools.partial(next, itertools.count(start=1))
        self._state = _DAPSessionState()

        self._event_history = EventHistory(self._message_timeout)
        self._adapter = adapter
        self._connection = adapter.create_connection()

        def on_connection_closed(err: Optional[Exception]):
            # We want fail early if is already a request for wait_for_X_event.
            self._event_history.close(err or Exception("Session Ended."))

        msg_handler = MessageHandler(
            on_response=self._on_protocol_response,
            on_event=self._on_protocol_event,
            on_reverse_request=self._on_protocol_reverse_request,
            on_close=on_connection_closed,
        )
        self._read_thread = threading.Thread(
            target=self._connection.start, args=[msg_handler], name="Read Thread"
        )

        # Function Mappings
        self.wait_for_first_event = self._event_history.wait_for_first_event
        self.wait_for_any_event = self._event_history.wait_for_any_event
        self.wait_for_event = self._event_history.wait_for_event
        self.capabilities = self._state.capabilities

        # Reverse Requests
        self._reverse_requests: list[Request] = []
        self._reverse_process: Optional[subprocess.Popen[bytes]] = None
        # TODO: add some explanation on what this field is used for.
        self._reverse_process_io_threads: list[threading.Thread] = []

    def last_response(self):
        """Returns a copy of the last response message"""
        response = self._state._last_response
        assert response is not None, "expected at least previous response"
        return dataclasses.replace(response)

    @property
    def stopped_thread_id(self):
        thread_id = self._state.stopped_thread_id
        assert thread_id is not None, "stopped thread id is never set"
        return thread_id

    def _current_stop_generation(self) -> int:
        return self._state.stop_generation

    def _check_stop_generation(self, ctx_generation: int, context: Any) -> None:
        """Assert a context generation is still valid for the current stop."""
        current = self._state.stop_generation
        if ctx_generation != current:
            raise AssertionError(
                f"{type(context).__name__} from stop generation {ctx_generation} used at "
                f"generation {current}: the session resumed, so "
                f"this context's frameId/variablesReference is no longer valid."
            )

    def start(self) -> None:
        """Start the connection"""
        self._read_thread.start()
        # Synchronize with the connection.
        self._connection.wait_until_alive(self._message_timeout)

    def _on_protocol_response(self, message: RawMessage) -> None:
        """Handle response message"""
        self._test_message_log.write(f"dap <- client {json.dumps(message)}\n")
        command = message.get("command")
        if command == InitializeArgs.command_:
            if raw_capabilities := message.get("body"):
                init_capabilities = dict_to_message(Capabilities, raw_capabilities)
                self._state.update_capabilities(init_capabilities)
        if message["command"] == DisconnectArgs.command_:
            self._connection.stop()

    def _on_protocol_event(self, message: RawMessage) -> None:
        """Handle event message"""
        self._test_message_log.write(f"dap <- client {json.dumps(message)}\n")

        event = Event.from_json(message)
        event_name = event.event
        assert event_name is not None

        if isinstance(event, InitializedEvent):
            self._state.set_initialized(True)
        elif isinstance(event, CapabilitiesEvent):
            self._state.update_capabilities(event.body.capabilities)
        elif isinstance(event, StoppedEvent):
            if (thread_id := event.body.threadId) and not event.body.preserveFocusHint:
                self._state.set_stopped_thread_id(thread_id)
        elif isinstance(event, OutputEvent):
            category = self._state.output_streams[event.body.category]
            category.write(event.body.output)
        elif isinstance(event, ExitedEvent):
            # If we have a 'runInTerminal' process it must have exited.
            if self._reverse_process:
                self.verify_reverse_process_exited()

                # Join the redirect threads here. so any tail bytes are flushed
                # into the StringIOs before the test reads them.
                for thread in self._reverse_process_io_threads:
                    thread.join(self._message_timeout)

        # Store in general event queue
        self._event_history.record(event)

    def _on_protocol_reverse_request(self, request: RawMessage):
        self._test_message_log.write(f"dap <- client {json.dumps(request)}\n")
        request_type = request.get("command", "unknown")
        if request_type == "runInTerminal":
            terminal_request = dict_to_message(RunInTerminalRequest, request)
            self._reverse_requests.append(terminal_request)
            self._handle_run_in_terminal(terminal_request)
        else:
            raise NotImplementedError(
                f"no reverse request handler for '{request_type}'"
            )

    def _handle_run_in_terminal(self, request: RunInTerminalRequest):
        terminal_args = request.arguments
        process_args = terminal_args.args
        env: dict[str, Any] = {}
        if terminal_args.env:
            for key, value in terminal_args.env.items():
                env[key] = "" if value is None else value

        self._test_message_log.write(f"runInTerminal process with args: {process_args}")
        process = subprocess.Popen(
            process_args,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return_code = process.poll()
        if return_code is not None:
            stdout, stderr = process.communicate()
            response = ErrorResponse(
                type=MessageType.RESPONSE,
                seq=self._next_sequence(),
                command=request.command,
                request_seq=request.seq,
                success=False,
                body=ErrorResponse.Body(
                    error=Message(
                        id=3,
                        format=f"failed to launch process {process_args[0]}, stdout={stdout}"
                        f"\nstderr={stderr} return code ={return_code}",
                    )
                ),
            )
        else:
            self._reverse_process = process
            response = RunInTerminalResponse(
                type=MessageType.RESPONSE,
                seq=self._next_sequence(),
                command="runInTerminal",
                request_seq=request.seq,
                success=True,
                body=RunInTerminalResponse.Body(processId=process.pid),
            )
            if proc_stdout := process.stdout:
                out_stream = self._state.output_streams[OutputCategory.STDOUT]
                out_thread = redirect_stream(proc_stdout, out_stream, "stdout")
                self._reverse_process_io_threads.append(out_thread)
            if proc_stderr := process.stderr:
                err_stream = self._state.output_streams[OutputCategory.STDERR]
                err_thread = redirect_stream(proc_stderr, err_stream, "stderr")
                self._reverse_process_io_threads.append(err_thread)

        self._send_response(response)

    def ensure_initialized(self):
        if self._state.is_initialized:
            return
        self.wait_for_first_event(InitializedEvent)
        # Sanity check
        assert self._state.is_initialized

    def get_stdout(self):
        return self._state.output_streams[OutputCategory.STDOUT].getvalue()

    def get_console(self) -> str:
        return self._state.output_streams[OutputCategory.CONSOLE].getvalue()

    def get_stderr(self) -> str:
        return self._state.output_streams[OutputCategory.STDERR].getvalue()

    def get_important(self) -> str:
        return self._state.output_streams[OutputCategory.IMPORTANT].getvalue()

    def send_request(
        self, request_args: ArgsProtocol[AnyResponse]
    ) -> ResponseHandle[AnyResponse]:
        """Send a request and wait for response"""
        assert isinstance(request_args, ArgsProtocol)
        seq = self._next_sequence()

        # Any frameId or variablesReference during this stop becomes stale once the request is sent.
        if type(request_args) in _RESUMING_COMMANDS:
            self._state.advance_stop_generation()

        request = Request(
            seq=seq,
            type=MessageType.REQUEST,
            command=request_args.command_,
            arguments=request_args if len(fields(request_args)) > 0 else None,
        )

        self._test_message_log.write(f"client -> dap {json.dumps(request.to_dict())}\n")
        self._connection.send_request(request)
        return ResponseHandle(seq, request_args.response_class_)

    def _send_response(self, response: ReverseResponse):
        assert isinstance(response, Response)
        response_dict = response.to_dict()
        self._test_message_log.write(f"{response_dict}\n")
        self._connection.send_message(response_dict)

    def get_response_or_error(
        self, handle: ResponseHandle[AnyResponse]
    ) -> Union[AnyResponse, ErrorResponse]:
        assert issubclass(handle.response_class, Response)
        raw_response = self._connection.get_response(handle.seq, self._message_timeout)

        if raw_response["success"] is False or handle.response_class is ErrorResponse:
            response_type = ErrorResponse
        else:
            response_type = handle.response_class
        response = response_type.from_json(raw_response)
        self._state._last_response = response

        return response

    def get_response(self, handle: ResponseHandle[AnyResponse]) -> AnyResponse:
        response = self.get_response_or_error(handle)
        if not isinstance(response, handle.response_class):
            raise DAPError(
                f"expected '{handle.response_class.__name__}' got response: {response}."
            )

        return response

    def get_error_response(self, handle: ResponseHandle) -> ErrorResponse:
        response = self.get_response_or_error(handle)
        if not isinstance(response, ErrorResponse):
            raise DAPError(
                f"expected '{handle.response_class.__name__}' got response: {response}."
            )

        return response

    def wait_for_event_from_last_response(
        self,
        event_type: Type[AnyEvent],
        until: Optional[Callable[[Event], bool]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> AnyEvent:
        response = self.last_response()

        return self._event_history.wait_for_event(
            event_type, after=response, until=until, timeout=timeout
        )

    def last_reverse_request(self) -> Request:
        assert len(self._reverse_requests) > 0, "No Reverse Request made"
        return self._reverse_requests[-1]

    def is_running(self):
        return self._connection.is_alive()

    def verify_reverse_process_exited(self, exit_code: Optional[int] = None):
        if process := self._reverse_process:
            proc_exit_code = process.poll()
            if proc_exit_code is None:
                raise DAPError(
                    f"process is still running, "
                    f"for process pid: '{process.pid}', args: {process.args}"
                )

            if exit_code is not None:
                assert proc_exit_code == exit_code, (
                    f"{proc_exit_code=} != expected_exit_code={exit_code} "
                    f"for process pid: '{process.pid}', args: {process.args}"
                )

    def stop(self) -> None:
        self._connection.stop()

        if self._read_thread.is_alive():
            self._read_thread.join(self._message_timeout)

        # If the runInTerminal subprocess is still alive the redirect threads are
        # blocked in read. Kill the process to stop thre redirect threads.
        reverse_process = self._reverse_process
        if (reverse_process := reverse_process) and reverse_process.poll() is None:
            reverse_process.terminate()
            try:
                reverse_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                reverse_process.kill()

        for thread in self._reverse_process_io_threads:
            thread.join(timeout=self._message_timeout)

        if not self._test_message_log.closed:
            self._test_message_log.flush()
            self._test_message_log.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
