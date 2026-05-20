from __future__ import annotations

import base64
import dataclasses
import os
from pathlib import Path
import unittest
from dataclasses import dataclass
from typing import (
    Callable,
    Iterator,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from lldb_dap.dap_types import (
    AnyBreakpointsResponse,
    AnyResponse,
    ArgsProtocol,
    AttachArgs,
    Breakpoint,
    BreakpointEvent,
    BreakpointLocationsArgs,
    CompletionsArgs,
    ConfigurationDoneArgs,
    ContinueArgs,
    DAPError,
    DataBreakpoint,
    DataBreakpointInfoArgs,
    DisassembleArgs,
    DisconnectArgs,
    EmptyBodyResponse,
    ErrorResponse,
    EvaluateArgs,
    EvaluateContext,
    Event,
    EventName,
    ExceptionInfoArgs,
    ExitedEvent,
    FunctionBreakpoint,
    InitializeArgs,
    InitializedEvent,
    InitializeResponse,
    InstructionBreakpoint,
    InvalidatedEvent,
    LaunchArgs,
    MemoryEvent,
    ModuleEvent,
    ModuleReason,
    ModulesArgs,
    NextArgs,
    OutputCategory,
    OutputEvent,
    ProcessEvent,
    ReadMemoryArgs,
    Response,
    RestartArgs,
    ScopesArgs,
    Scope,
    SetBreakpointsArgs,
    SetDataBreakpointsArgs,
    SetFunctionBreakpointsArgs,
    SetInstructionBreakpointsArgs,
    SetVariableArgs,
    SetVariableResponse,
    Source,
    SourceBreakpoint,
    StackFrame,
    StackFrameFormat,
    StackTraceArgs,
    StepInArgs,
    StepOutArgs,
    SteppingGranularity,
    StoppedEvent,
    StoppedReason,
    TerminatedEvent,
    ThreadsArgs,
    ValueFormat,
    Variable,
    VariablesArgs,
    WriteMemoryArgs,
)
from lldb_dap.utils import DebugAdapter

from .session import ResponseHandle, Session

T = TypeVar("T")


class ThreadContext:
    """Lazy view of a debug adapter thread.

    Thread ids do not have a limited lifetime, so this context is long-lived: it can
    be reused after continues and steps. Frames, scopes, and variables lifetimes are limited
    to the current suspended state of the session and needs to be requested once execution
    resumes.
    """

    def __init__(self, thread_id: int, session: DAPTestSession):
        self._thread_id: int = thread_id
        self._session: DAPTestSession = session

    @property
    def thread_id(self) -> int:
        return self._thread_id

    def step_in(
        self,
        *,
        targetId: Optional[int] = None,
        granularity: SteppingGranularity = "statement",
    ):
        return self._session.step_in(
            threadId=self.thread_id, targetId=targetId, granularity=granularity
        )

    def step_over(self, *, granularity: SteppingGranularity = "statement"):
        return self._session.step_over(threadId=self.thread_id, granularity=granularity)

    def step_out(self, *, granularity: SteppingGranularity = "statement"):
        return self._session.step_out(threadId=self.thread_id, granularity=granularity)

    def top_frame(self) -> FrameContext:
        return self.frames(levels=1)[0]

    def frames(
        self,
        *,
        startFrame: Optional[int] = None,
        levels: Optional[int] = None,
        format: Optional[StackFrameFormat] = None,
    ) -> list[FrameContext]:
        response = self._session.request_and_respond(
            StackTraceArgs(
                self._thread_id, startFrame=startFrame, levels=levels, format=format
            )
        )
        generation = self._session._current_stop_generation()
        return [
            FrameContext(frame, self._session, generation)
            for frame in response.body.stackFrames
        ]


class FrameContext:
    """Lazy view of a stack frame. Valid only within its stop generation."""

    def __init__(self, frame: StackFrame, session: DAPTestSession, generation: int):
        self._frame = frame
        self._session = session
        self._generation = generation
        self._scopes: Optional[list[ScopeContext]] = None

    @property
    def frame(self) -> StackFrame:
        self._session._check_stop_generation(self._generation, self)
        return self._frame

    @property
    def id(self) -> int:
        return self.frame.id

    def __dir__(self):
        # Hide the property fields that may call 'ScopesRequest' from the debugger.
        # The debugger will hang because it is waiting for a response when viewing the FrameContext.
        hidden = {"locals", "globals", "registers", "scopes"}
        return (attr for attr in super().__dir__() if attr not in hidden)

    def source_and_line(self) -> tuple[str, int]:
        frame = self.frame
        assert frame.source is not None
        assert frame.source.path is not None
        assert frame.line is not None
        return frame.source.path, frame.line

    def scopes(self) -> list[ScopeContext]:
        self._session._check_stop_generation(self._generation, self)
        if self._scopes is None:
            response = self._session.request_and_respond(
                ScopesArgs(frameId=self._frame.id)
            )
            self._scopes = [
                ScopeContext(scope, self._session, self._generation)
                for scope in response.body.scopes
            ]
        return self._scopes

    def scope(self, name: str) -> ScopeContext:
        scopes = self.scopes()
        for scope in scopes:
            if scope.scope.name == name:
                return scope
        scope_names = [scope.scope.name for scope in scopes]
        self._session.test_case.fail(
            f"scope '{name}' not in frame scopes: {scope_names}"
        )

    @property
    def locals(self) -> ScopeContext:
        return self.scope("Locals")

    @property
    def globals(self) -> ScopeContext:
        return self.scope("Globals")

    @property
    def registers(self) -> ScopeContext:
        return self.scope("Registers")

    def evaluate(
        self,
        expression: str,
        *,
        context: Optional[EvaluateContext] = None,
        format: Optional[ValueFormat] = None,
    ):
        """Evaluates `expression` in this frame's context."""
        self._session._check_stop_generation(self._generation, self)
        return self._session.evaluate(
            expression, frameId=self._frame.id, context=context, format=format
        )

    def disassemble(self):
        mem_ref = self._frame.instructionPointerReference
        if mem_ref is None:
            self._session.test_case.fail(
                f"expects 'instructionPointerReference' for frame {self.frame}"
            )
        return self._session.send_disassemble(
            mem_ref, instructionOffset=0, instructionCount=100
        )


class _VariableContainer:
    """Shared dict-like behaviour for contexts that hold a variablesReference.

    The optional `_value_format` is threaded into every child-fetching
    `variables` request. A child `VariableContext` inherits its parent's
    format, so walking ``locals.with_format(hex)["pt"]["x"]`` keeps hex
    formatting all the way down without the caller repeating it at each step.
    """

    _session: DAPTestSession
    _generation: int
    _value_format: Optional[ValueFormat] = None

    def _fetch_variables(
        self,
        variables_reference: int,
        *,
        filter: Optional[Literal["indexed", "named"]] = None,
        start: Optional[int] = None,
        count: Optional[int] = None,
    ) -> list[VariableContext]:
        self._session._check_stop_generation(self._generation, self)
        response = self._session.request_and_respond(
            VariablesArgs(
                variables_reference,
                filter=filter,
                start=start,
                count=count,
                format=self._value_format,
            )
        )
        return [
            VariableContext(var, self._session, self._generation, self._value_format)
            for var in response.body.variables
        ]

    def page(
        self,
        *,
        filter: Optional[Literal["indexed", "named"]] = None,
        start: Optional[int] = None,
        count: Optional[int] = None,
    ) -> list[VariableContext]:
        """Fetch a subset of children with paging/filter arguments.

        Inherits the container's value format.
        """
        return self._fetch_variables(
            self._container_reference(),
            filter=filter,
            start=start,
            count=count,
        )

    def set(self, name: str, value, *, is_hex: bool = False) -> SetVariableResponse:
        """Sends a `setVariable` request for a named child.
        """
        self._session._check_stop_generation(self._generation, self)
        return self._session.request_and_respond(
            SetVariableArgs(
                variablesReference=self._container_reference(),
                name=name,
                value=str(value),
                format=ValueFormat(hex=True) if is_hex else None,
            )
        )

    def _container_reference(self) -> int:
        raise NotImplementedError

    def _by_name(self) -> dict[str, VariableContext]:
        return {child.name: child for child in self._children()}

    def _children(self) -> list[VariableContext]:
        raise NotImplementedError

    def __getitem__(self, name: str) -> VariableContext:
        by_name = self._by_name()
        try:
            return by_name[name]
        except KeyError:
            self._session.test_case.fail(
                f"'{name}' not found in {self._describe()}, has: {list(by_name)}"
            )

    def __contains__(self, name: object) -> bool:
        return name in self._by_name()

    def __iter__(self) -> Iterator[VariableContext]:
        return iter(self._children())

    def __len__(self) -> int:
        return len(self._children())

    def _describe(self) -> str:
        return type(self).__name__


class ScopeContext(_VariableContainer):
    """Lazy view of a scope's variables. Valid only within its stop generation."""

    def __init__(
        self,
        scope: Scope,
        session: DAPTestSession,
        generation: int,
        value_format: Optional[ValueFormat] = None,
    ):
        self._scope = scope
        self._session = session
        self._generation = generation
        self._value_format = value_format

    @property
    def scope(self) -> Scope:
        self._session._check_stop_generation(self._generation, self)
        return self._scope

    @property
    def name(self) -> str:
        return self.scope.name

    @property
    def variablesReference(self) -> int:
        return self.scope.variablesReference

    def variables(self) -> list[VariableContext]:
        return self._fetch_variables(self._scope.variablesReference)

    def with_format(self, *, is_hex: bool = False) -> ScopeContext:
        """Return a new ScopeContext whose variables requests use these args.

        Keyword-only by design so new args can be added without breaking
        callers. Today ``is_hex`` toggles ValueFormat.hex; adding e.g. a
        stop/display knob is an additive change to this signature.
        """
        value_format = ValueFormat(hex=True) if is_hex else None
        return ScopeContext(self._scope, self._session, self._generation, value_format)

    def _container_reference(self) -> int:
        return self._scope.variablesReference

    def _children(self) -> list[VariableContext]:
        return self.variables()

    def _describe(self) -> str:
        return f"scope '{self._scope.name}'"


class VariableContext(_VariableContainer):
    """Lazy view of a variable and (optionally) its children.

    Valid only within its' stop generation.
    """

    def __init__(
        self,
        variable: Variable,
        session: DAPTestSession,
        generation: int,
        value_format: Optional[ValueFormat] = None,
    ):
        self._variable = variable
        self._session = session
        self._generation = generation
        self._value_format = value_format

    @property
    def variable(self) -> Variable:
        self._session._check_stop_generation(self._generation, self)
        return self._variable

    @property
    def name(self) -> str:
        return self._variable.name

    @property
    def value(self) -> str:
        return self._variable.value

    @property
    def value_as_int(self) -> int:
        return self._variable.value_as_int

    @property
    def type(self) -> Optional[str]:
        return self._variable.type

    @property
    def variablesReference(self) -> int:
        return self._variable.variablesReference

    @property
    def memoryReference(self) -> Optional[str]:
        return self._variable.memoryReference

    @property
    def indexedVariables(self) -> Optional[int]:
        return self._variable.indexedVariables

    @property
    def namedVariables(self) -> Optional[int]:
        return self._variable.namedVariables

    @property
    def has_children(self) -> bool:
        return self._variable.variablesReference > 0

    def children(self) -> list[VariableContext]:
        if not self.has_children:
            self._session.test_case.fail(
                f"variable '{self._variable.name}' has no children"
            )
        return self._fetch_variables(self._variable.variablesReference)

    def with_format(self, *, is_hex: bool = False) -> VariableContext:
        """Return a new VariableContext that applies the ValueFormat"""
        value_format = ValueFormat(hex=True) if is_hex else None
        return VariableContext(
            self._variable, self._session, self._generation, value_format
        )

    def _container_reference(self) -> int:
        return self._variable.variablesReference

    def _children(self) -> list[VariableContext]:
        return self.children()

    def _describe(self) -> str:
        return f"variable '{self._variable.name}'"


@dataclass(frozen=True)
class CapturedOutput:
    seen_texts: str
    """The accumulated text until matched pattern (included)."""
    event: OutputEvent
    """The event containing the matched pattern"""


class _ConfigureContext:
    """Handles the initial launch sequence handshake.

    Orchestrates the full DAP initialization sequence:
    On enter:
        - Request and respond to the `Initialize` command.
        - Send launch/attach request.
        - Wait for InitializedEvent.

    In between:
       The test can set breakpoints or perform any check it needs do.

    On exit:
        4. Set and verify the pending source and function breakpoints.
        5. Request and response to configurationDone.
        6. Wait for ProcessEvent and launch/attach response.

    Example:

      >>> session.configure(LaunchArgs(program="a.out")) as ctx:
      ...     session.resolve_function_breakpoints(["do_foo"])
      >>> process_event = ctx.process_event()
    """

    def __init__(
        self,
        session: "DAPTestSession",
        config: LaunchArgs | AttachArgs,
    ):
        self._session = session
        self._config = config
        self._init_response: Optional[InitializeResponse] = None
        self._request_handle: Optional[ResponseHandle[EmptyBodyResponse]] = None
        self._process_event: Optional[ProcessEvent] = None
        self._response: Optional[EmptyBodyResponse] = None

    def __enter__(self) -> "_ConfigureContext":
        session = self._session
        session.test_case.assertFalse(
            session._state.is_initialized, "session already started."
        )
        self._init_response = session.initialize_sequence(session.initialize_args)
        self._request_handle = session.send_request(self._config)
        session.wait_for_event(InitializedEvent, after=self._init_response)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            return False

        session = self._session
        assert self._init_response is not None
        assert self._request_handle is not None

        session.verify_configuration_done()
        proc_event = session.wait_for_event(ProcessEvent, after=self._init_response)

        if start_method := proc_event.body.startMethod:
            session.test_case.assertIn(
                start_method,
                ("launch", "attach"),
                f"expected launch or attach got '{start_method}'",
            )

        self._process_event = proc_event
        self._response = session.get_response(self._request_handle)
        return False

    def process_event(self) -> ProcessEvent:
        """Return the ``ProcessEvent`` captured on context exit.

        Must be called after the ``with`` block has exited.
        """
        # TODO: make this a property?
        if self._process_event is None:
            raise DAPError(
                "ConfigureContext.process_event() called before the context exited"
            )
        return self._process_event

    def launch_or_attach_response(self) -> EmptyBodyResponse:
        """Return the response to the launch/attach request.

        Must be called after the ``with`` block has exited.
        """
        if self._response is None:
            raise DAPError(
                "ConfigureContext.launch_or_attach_response() called before the context exited"
            )
        return self._response


class DAPTestSession(Session):
    """Common DAP test scenarios"""

    def __init__(
        self,
        test_case: unittest.TestCase,
        test_dir: Path,
        adapter: DebugAdapter,
        message_timeout: float,
        log_file: Optional[str] = None,
    ):
        Session.__init__(self, test_dir, adapter, message_timeout, log_file)
        self.test_case = test_case

        # The default features that lldb supports
        # When a test does not explicitly set initialize args this is used.
        self._init_args = InitializeArgs(
            adapterID="lldb-native",
            clientID="vscode",
            columnsStartAt1=True,
            linesStartAt1=True,
            locale="en-us",
            pathFormat="path",
            supportsRunInTerminalRequest=True,
            supportsVariablePaging=True,
            supportsVariableType=True,
            supportsStartDebuggingRequest=True,
            supportsProgressReporting=True,
            supportsInvalidatedEvent=True,
            supportsMemoryEvent=True,
        )

    def update_initialize_args(self, **kwargs):
        self.test_case.assertFalse(
            self._state.is_initialized,
            "session already initialized cannot update initialize args.",
        )

        self._init_args = dataclasses.replace(self._init_args, **kwargs)

    @property
    def initialize_args(self):
        return dataclasses.replace(self._init_args)

    def start_debug_session(self, config: LaunchArgs | AttachArgs):
        with self.configure(config) as ctx:
            pass
        # We are returning the process event as it contains more information
        # than the (launch/attach) response and we may get the stop on entry event before the (launch/attach) response.
        # and most of the test only do something after we have a process.
        return ctx.process_event()

    def launch_using_config(self, config: LaunchArgs):
        return self.start_debug_session(config)

    def attach_using_config(self, config: AttachArgs):
        return self.start_debug_session(config)

    def configure(self, config: LaunchArgs | AttachArgs) -> _ConfigureContext:
        """Return a context that scopes the startup handshake.

        Inside the ``with`` block, call ``set_source_breakpoints`` /
        ``set_function_breakpoints`` as needed. After the block exits,
        use ``ctx.process_event()`` and ``ctx.launch_or_attach_response()``
        to retrieve the results.

        Example:
            >>> with session.configure(LaunchArgs(program)) as ctx:
            ...     session.set_source_breakpoints("main.cpp", [10, 25])
            >>> process_event = ctx.process_event()
            >>> response = ctx.launch_or_attach_response()
        """
        return _ConfigureContext(self, config)

    def request_and_respond(
        self, request_args: ArgsProtocol[AnyResponse]
    ) -> AnyResponse:
        handle = self.send_request(request_args)
        return self.get_response(handle)

    def request_and_error_response(
        self, request_args: ArgsProtocol[AnyResponse]
    ) -> ErrorResponse:
        request_handle = self.send_request(request_args)
        return self.get_error_response(request_handle)

    def initialize_sequence(self, initialize_args: InitializeArgs):
        # Send initialize
        init_response = self.request_and_respond(initialize_args)
        self.test_case.assertIsNotNone(init_response)
        return init_response

    def initialize_and_launch(self, args: LaunchArgs | AttachArgs):
        # TODO: check the test that uses this function if it is still necessary.
        self.initialize_sequence(self.initialize_args)
        return self.send_request(args)

    def configuration_done(self):
        # Wait for initialized event
        self.ensure_initialized()
        # Send configuration done
        handle = self.send_request(ConfigurationDoneArgs())
        return self.get_response_or_error(handle)

    def verify_configuration_done(self, expected_success: bool = True):
        response = self.configuration_done()
        if expected_success:
            self.test_case.assertEqual(
                response.success, True, f"got error response {response}"
            )
            self.test_case.assertIsInstance(response, EmptyBodyResponse)

            # In VSCode, immediately following 'configurationDone', a
            # 'threads' request is made to get the initial set of threads,
            # specifically the main threads id and name.
            # We issue the threads request to mimic this pattern and prevent
            # tests that uses threads to have the wrong result.
            self.request_and_respond(ThreadsArgs())
        else:
            self.test_case.assertEqual(response.success, False)
            self.test_case.assertIsInstance(response, ErrorResponse)
        return response

    def attach_and_configuration_done(self, attach_args: AttachArgs):
        attach_handle = self.send_request(attach_args)
        self.verify_configuration_done()

        return self.get_response(attach_handle)

    def set_source_breakpoints(
        self, source_path: str, breakpoints: list[int] | list[SourceBreakpoint]
    ):
        self.ensure_initialized()
        # we convert the deprecated lines field to SourceBreakpoints.
        if all(isinstance(bp, int) for bp in breakpoints):
            breakpoints = cast(List[int], breakpoints)
            breakpoints = [SourceBreakpoint(line) for line in breakpoints]

        if any(not isinstance(bp, SourceBreakpoint) for bp in breakpoints):
            self.test_case.fail(
                "breakpoints must only contain ints or SourceBreakpoints."
                f" got: {breakpoints}"
            )

        bps = cast(List[SourceBreakpoint], breakpoints)
        bp_args = SetBreakpointsArgs(
            source=Source.create(path=source_path), breakpoints=bps
        )
        response = self.request_and_respond(bp_args)
        return response

    def set_function_breakpoints(
        self,
        function_names: list[str],
        condition: Optional[str] = None,
        hit_condition: Optional[str] = None,
    ):
        f_breakpoints = [
            FunctionBreakpoint(name, condition=condition, hitCondition=hit_condition)
            for name in function_names
        ]
        response = self.request_and_respond(SetFunctionBreakpointsArgs(f_breakpoints))
        return response

    def resolve_source_breakpoints(
        self, source_path: str, breakpoints: list[int] | list[SourceBreakpoint]
    ):
        last_response = self.last_response()
        bp_response = self.set_source_breakpoints(source_path, breakpoints)

        resp_breakpoints = bp_response.body.breakpoints
        pending_breakpoint_ids: list[int] = []
        verified_breakpoint_ids: list[int] = []
        for breakpoint in resp_breakpoints:
            assert breakpoint.id is not None

            if breakpoint.verified:
                verified_breakpoint_ids.append(breakpoint.id)
            else:
                pending_breakpoint_ids.append(breakpoint.id)

        if len(pending_breakpoint_ids) > 0:
            self.wait_until_all_breakpoints_verified(
                pending_breakpoint_ids, after=last_response
            )

        # Returns all the ids since they are both verified and resolved.
        all_ids = [*pending_breakpoint_ids, *verified_breakpoint_ids]

        self.test_case.assertEqual(
            len(breakpoints), len(all_ids), "expect correct number of breakpoints"
        )
        return all_ids

    def resolve_function_breakpoints(
        self,
        function_names: list[str],
        condition: Optional[str] = None,
        hit_condition: Optional[str] = None,
    ) -> List[int]:
        """Sets breakpoints by function name given an array of function names
        and returns an array of strings containing the breakpoint IDs
        ("1", "2") for each breakpoint that was set.
        """
        last_response = self.last_response()
        response = self.set_function_breakpoints(
            function_names, condition, hit_condition
        )
        breakpoints = response.body.breakpoints

        def breakpoints_to_ids(breakpoints: list[Breakpoint]):
            ids: list[int] = []
            for bp in breakpoints:
                assert bp.id is not None, f"id is None for breakpoint: {bp}"
                ids.append(bp.id)
            return ids

        all_verified = all(bp.verified for bp in breakpoints)
        if not all_verified:
            # Use the response from before the 'setFunction' request for verification,
            # as a breakpoint event could be received prior to the 'setFunction' response.
            self.wait_until_all_breakpoints_verified(breakpoints, after=last_response)

        return breakpoints_to_ids(breakpoints)

    def set_data_breakpoints(self, breakpoints: list[DataBreakpoint]):
        return self.request_and_respond(SetDataBreakpointsArgs(breakpoints=breakpoints))

    def set_instruction_breakpoints(self, memory_references: list[str]):
        breakpoints = [InstructionBreakpoint(ref) for ref in memory_references]
        return self.request_and_respond(SetInstructionBreakpointsArgs(breakpoints))

    def set_breakpoint_locations(
        self,
        file_path: str,
        line: int,
        column: Optional[int] = None,
        endLine: Optional[int] = None,
        endColumn: Optional[int] = None,
    ):
        _, name = os.path.split(file_path)
        return self.request_and_respond(
            BreakpointLocationsArgs(
                Source(name=name, path=file_path),
                line=line,
                column=column,
                endLine=endLine,
                endColumn=endColumn,
            )
        )

    def data_breakpoint_info(self, name: str, variablesReference: int, frameId: int):
        info_args = DataBreakpointInfoArgs(
            name=name, variablesReference=variablesReference, frameId=frameId
        )
        return self.request_and_respond(info_args)

    def data_breakpoint_info_as_address(self, address: str, size: int):
        info_args = DataBreakpointInfoArgs(name=address, bytes=size, asAddress=True)
        return self.request_and_respond(info_args)

    def step_in(
        self,
        threadId: Optional[int] = None,
        *,
        targetId: Optional[int] = None,
        granularity: SteppingGranularity = "statement",
    ):
        thread_id = self.stopped_thread_id if threadId is None else threadId
        self.test_case.assertIsNotNone(thread_id)
        stepin_args = StepInArgs(
            threadId=thread_id, targetId=targetId, granularity=granularity
        )
        response = self.request_and_respond(stepin_args)
        stop_event = self.verify_stopped(StoppedReason.STEP, after=response)
        return stop_event

    def step_over(
        self,
        threadId: Optional[int] = None,
        *,
        granularity: SteppingGranularity = "statement",
    ):
        thread_id = self.stopped_thread_id if threadId is None else threadId
        self.test_case.assertIsNotNone(thread_id)
        next_args = NextArgs(threadId=thread_id, granularity=granularity)
        response = self.request_and_respond(next_args)
        stop_event = self.verify_stopped(StoppedReason.STEP, after=response)
        return stop_event

    def step_out(
        self,
        threadId: Optional[int] = None,
        *,
        granularity: SteppingGranularity = "statement",
    ):
        thread_id = self.stopped_thread_id if threadId is None else threadId
        self.test_case.assertIsNotNone(thread_id)
        step_out_args = StepOutArgs(threadId=thread_id, granularity=granularity)
        response = self.request_and_respond(step_out_args)

        stop_event = self.verify_stopped(StoppedReason.STEP, after=response)
        return stop_event

    def wait_until_any_breakpoint_hit(
        self, breakpoint_ids: list[int], *, after: Event | Response
    ) -> StoppedEvent:
        """Wait for the process to send 'StoppedEvents' and verify we stopped for
        any breakpoint in breakpoint_ids the event or response.
        """

        self.test_case.assertGreater(len(breakpoint_ids), 0, "got empty breakpoint ids")
        is_ids_int = all(isinstance(id, int) for id in breakpoint_ids)
        self.test_case.assertTrue(is_ids_int, "all breakpoint_ids must be integers")

        breakpoint_stop_reasons = [
            StoppedReason.BREAKPOINT,
            StoppedReason.INSTRUCTION_BREAKPOINT,
            StoppedReason.FUNCTION_BREAKPOINT,
            StoppedReason.DATA_BREAKPOINT,
        ]
        timeout_msg = f"waiting for breakpoint hit with any id {breakpoint_ids}, after seq {after.seq}"

        def event_hit_id_in_breakpoint_ids(event: StoppedEvent):
            hit_ids = event.body.hitBreakpointIds or []
            for hit_id in hit_ids:
                if hit_id in breakpoint_ids:
                    return True

            return False

        event = self.wait_for_stopped(
            breakpoint_stop_reasons,
            after=after,
            until=event_hit_id_in_breakpoint_ids,
            timeout_msg=timeout_msg,
        )

        return event

    def verify_multiple_breakpoints_hit(
        self, breakpoint_ids: list[int], *, after: Event | Response
    ) -> StoppedEvent:
        """Wait for the process to send 'StoppedEvents' and verify we stopped for
        any breakpoint in breakpoint_ids the event or response.
        """

        self.test_case.assertGreater(len(breakpoint_ids), 0, "got empty breakpoint ids")
        is_ids_int = all(isinstance(id, int) for id in breakpoint_ids)
        self.test_case.assertTrue(is_ids_int, "all breakpoint_ids must be integers")

        event = self.verify_stopped_on_breakpoint(after=after)
        hit_ids = event.body.hitBreakpointIds or []
        if all(bp_id in hit_ids for bp_id in breakpoint_ids):
            return event

        self.test_case.fail(f"multiple breakpoints not hit, event: {event}")

    def wait_until_all_breakpoints_verified(
        self, breakpoints: list[int] | list[Breakpoint], *, after: Event | Response
    ):
        """Wait for the process to send breakpoint events and verify we hit
        all 'ids' in 'breakpoints' after the event or response.
        """
        assert len(breakpoints) > 0, "empty list of breakpoints"

        if all(isinstance(bp, Breakpoint) for bp in breakpoints):
            breakpoints = cast(List[Breakpoint], breakpoints)
            id_to_bp = {bp.id: bp.verified for bp in breakpoints}
        elif all(isinstance(bp, int) for bp in breakpoints):
            breakpoint_ids = cast(List[int], breakpoints)
            id_to_bp = {id: False for id in breakpoint_ids}
        else:
            raise AssertionError(
                f"expected list of 'Breakpoint' or breakpoint_ids got '{breakpoints}'"
            )

        def all_breakpoints_verified(evt: BreakpointEvent):
            event_bp = evt.body.breakpoint
            if event_bp.id is None:
                return False

            if event_bp.id not in id_to_bp.keys():
                return False
            id_to_bp[event_bp.id] = event_bp.verified

            all_verified = all(verified for (_, verified) in id_to_bp.items())
            return all_verified

        timeout_msg = f"waiting for all breakpoint ids {id_to_bp.keys()} to be verified"
        last_breakpoint_event = self.wait_for_event(
            BreakpointEvent,
            after=after,
            until=all_breakpoints_verified,
            timeout_msg=timeout_msg,
        )
        return last_breakpoint_event

    def wait_for_stopped_or_exited(
        self,
        *,
        after: Event | Response,
        until: Optional[Callable[[Union[StoppedEvent, ExitedEvent]], bool]] = None,
        timeout_msg: Optional[str] = None,
    ) -> StoppedEvent | ExitedEvent:
        event = self.wait_for_any_event(
            (StoppedEvent, ExitedEvent),
            after=after,
            until=until,
            timeout_msg=timeout_msg,
        )
        return event

    def wait_for_stopped(
        self,
        matching_any: Optional[Sequence[StoppedReason]] = None,
        *,
        after: Event | Response,
        until: Optional[Callable[[StoppedEvent], bool]] = None,
        timeout_msg: Optional[str] = None,
    ):
        """
        Wait for a process to stop, optionally filtered by stop reason and custom condition.

        Blocks until a StoppedEvent is received after the specified event. If matching_any
        is provided, only stops with those reasons are accepted. The until callback allows
        additional condition checking. If an ExitedEvent is encountered, wait_for terminates.

        Args:
            matching_any: Filter by specific stop reasons.
            after: Event or Response to start waiting after.
            until: Optional callback for additional filtering.
            timeout_msg: Custom timeout error message.
        """
        if matching_any:
            self.test_case.assertGreater(
                len(matching_any), 0, "expected at least one stop reason."
            )

        def matches_any_reason_until(event: StoppedEvent | ExitedEvent):
            # Break early for exited event.
            # We cannot hit a stopped event after the process exited.
            if isinstance(event, ExitedEvent):
                return True

            # Match any of the stopped reasons.
            if matching_any and event.body.reason not in matching_any:
                return False

            if until:
                return until(event)

            return True

        event = self.wait_for_stopped_or_exited(
            after=after, until=matches_any_reason_until, timeout_msg=timeout_msg
        )

        self.test_case.assertIsInstance(event, StoppedEvent, f"after seq: {after.seq}")
        self.test_case.assertEqual(event.event, EventName.STOPPED)
        return cast(StoppedEvent, event)

    def wait_for_exited(self, *, after: Event | Response) -> ExitedEvent:
        """
        Wait for a process to exit.

        Blocks until an ExitedEvent is received following the given event or response.
        Raises an error if a StoppedEvent is encountered, as a stopped process
        cannot subsequently exit.
        """
        event = self.wait_for_stopped_or_exited(after=after)
        self.test_case.assertIsInstance(event, ExitedEvent)
        self.test_case.assertEqual(event.event, "exited", "expected ExitedEvent'")
        return cast(ExitedEvent, event)

    def verify_next_module_event(
        self,
        reason: Optional[ModuleReason] = None,
        *,
        after: Event | Response,
    ):
        event = self.wait_for_module_event(after=after)
        event_body = event.body
        if reason is not None:
            self.test_case.assertEqual(
                event_body.reason,
                reason,
                f"module event reason does not match, got {event_body}.",
            )
        return event

    def wait_for_module_event(
        self,
        *,
        after: Event | Response,
        until: Optional[Callable[[ModuleEvent], bool]] = None,
    ):
        return self.wait_for_event(ModuleEvent, after=after, until=until)

    def wait_for_breakpoint_event(self, *, after: Event | Response):
        return self.wait_for_event(BreakpointEvent, after=after)

    def wait_for_terminated(self, *, after: Event | Response):
        return self.wait_for_event(TerminatedEvent, after=after)

    def wait_for_invalidated(self, *, after: Event | Response):
        return self.wait_for_event(InvalidatedEvent, after=after)

    def wait_for_memory_from(self, *, after: Event | Response):
        return self.wait_for_event(MemoryEvent, after=after)

    def do_continue(self):
        self.ensure_initialized()
        return self.request_and_respond(ContinueArgs())

    def continue_to_exit(self, exitCode: int = 0) -> ExitedEvent:
        continue_response = self.do_continue()
        return self.verify_process_exited(after=continue_response, exitCode=exitCode)

    def continue_to_breakpoint(self, breakpoint_id: int):
        return self.continue_to_any_breakpoint([breakpoint_id])

    def continue_to_any_breakpoint(self, breakpoint_ids: list[int]):
        response = self.do_continue()
        event = self.wait_until_any_breakpoint_hit(breakpoint_ids, after=response)
        return event

    def continue_to_next_stop(
        self, *, exp_reason: Optional[StoppedReason] = None
    ) -> StoppedEvent:
        """Continue execution and wait for stopped event"""
        response = self.do_continue()
        if exp_reason is not None:
            return self.verify_stopped(exp_reason, after=response)

        return self.wait_for_stopped(after=response)

    def evaluate(
        self,
        expression: str,
        *,
        frameId: Optional[int] = None,
        context: Optional[EvaluateContext] = None,
        format: Optional[ValueFormat] = None,
    ):
        eval_args = EvaluateArgs(
            expression=expression, frameId=frameId, context=context, format=format
        )
        handle = self.send_request(eval_args)
        response = self.get_response_or_error(handle)
        if isinstance(response, ErrorResponse):
            error = response.body
            self.test_case.fail(
                f"failed to evaluate `{expression}` in context '{context}'. error: {error}"
            )

        return response.body

    def collect_output_until(
        self,
        pattern: str,
        category: OutputCategory,
        *,
        after: Event | Response,
        timeout_msg: Optional[str] = None,
    ) -> CapturedOutput:
        """Wait for an output from the output_category matching the until_pattern.
        Args:
            pattern:
                return once this pattern is detected in the collected output.
            category: The category to collect.
        Returns:
            a tuple fo the collected output and the event with the pattern.
        """
        self.test_case.assertTrue(pattern, "expected a pattern")

        seen_outputs = []

        def matches_pattern(event: OutputEvent):
            event_body = event.body
            if event_body.category != category:
                return False

            event_output = event_body.output
            seen_outputs.append(event_output)

            in_output = pattern in event_output
            return in_output

        timeout_msg = f"{timeout_msg}\n\t" if timeout_msg else ""
        timeout_msg += (
            f"collecting output category '{category}' "
            f"until found pattern: '{pattern}'."
        )

        event = self.wait_for_event(
            OutputEvent, after=after, until=matches_pattern, timeout_msg=timeout_msg
        )
        # Sanity check.
        self.test_case.assertIsInstance(event, OutputEvent)

        return CapturedOutput(seen_texts="".join(seen_outputs), event=event)

    def collect_console_until(self, pattern: str, *, after: Event | Response):
        return self.collect_output_until(pattern, OutputCategory.CONSOLE, after=after)

    def collect_stdout_until(self, pattern: str, *, after: Event | Response):
        return self.collect_output_until(pattern, OutputCategory.STDOUT, after=after)

    def collect_important_until(self, pattern: str, *, after: Event | Response):
        return self.collect_output_until(pattern, OutputCategory.IMPORTANT, after=after)

    def verify_stopped(self, any_reason: StoppedReason, *, after: Event | Response):
        timeout_msg = f"waiting for 'StoppedEvent' for reason: {any_reason}"
        stopped_event = self.wait_for_stopped(after=after, timeout_msg=timeout_msg)
        event_body = stopped_event.body

        self.test_case.assertEqual(event_body.reason, any_reason, f"got {event_body}")
        return stopped_event

    def verify_stopped_on_breakpoint(
        self, expected_ids: Optional[List[int]] = None, *, after: Event | Response
    ):
        bp_reasons = [
            StoppedReason.BREAKPOINT,
            StoppedReason.DATA_BREAKPOINT,
            StoppedReason.FUNCTION_BREAKPOINT,
            StoppedReason.INSTRUCTION_BREAKPOINT,
        ]
        timeout_msg = f"waiting for 'StoppedEvent' for any breakpoint: {bp_reasons}"
        stopped_event = self.wait_for_stopped(after=after, timeout_msg=timeout_msg)
        event_body = stopped_event.body

        self.test_case.assertIn(event_body.reason, bp_reasons, f"got {event_body}")
        if expected_ids:
            fail_msg = f"expect breakpoint id(s) {expected_ids}"
            self.test_case.assertIsNotNone(event_body.hitBreakpointIds, fail_msg)
            hit_bp_ids = cast(List[int], event_body.hitBreakpointIds)

            for expected_id in expected_ids:
                fail_msg = f"expected breakpoint id not found in {expected_ids}"
                self.test_case.assertIn(expected_id, hit_bp_ids, fail_msg)

        return stopped_event

    def verify_stopped_on_entry(self, *, after: Event | Response):
        stop_event = self.verify_stopped(StoppedReason.ENTRY, after=after)
        return stop_event

    def verify_stopped_on_exception(
        self,
        *,
        after: Event | Response | None = None,
        expected_description: str,
        expected_text: Optional[str] = None,
    ):
        """Wait for the debuggee to stop, and verify the stop reason is
        'exception' with the description matching 'expected_description' and
        text match 'expected_text', if specified."""
        message = after if after is not None else self.last_response()

        # Wait for the first stopped event instead of one with the reason 'exception'
        # as the debuggee cannot will not continue after a stopped event.
        stopped_event = self.verify_stopped(StoppedReason.EXCEPTION, after=message)
        event_body = stopped_event.body

        self.test_case.assertIsNotNone(
            event_body.description,
            f"stopped event missing description {event_body}",
        )
        description = cast(str, event_body.description)

        fail_msg = f"for stopped event {event_body!r}"
        self.test_case.assertRegex(description, expected_description, fail_msg)

        if expected_text is not None:
            self.test_case.assertIsNotNone(event_body.text, fail_msg)
            text = cast(str, event_body.text)
            self.test_case.assertRegex(text, expected_text, fail_msg)

        return stopped_event

    def verify_process_exited(
        self, *, after: Event | Response | None = None, exitCode: int = 0
    ):
        message = after if after is not None else self.last_response()
        event = self.wait_for_exited(after=message)

        fail_msg = f"expect exitCode == '{exitCode}' for '{event.body}'"
        self.test_case.assertEqual(event.body.exitCode, exitCode, fail_msg)

        self.verify_reverse_process_exited(exitCode)
        return event

    def verify_commands(self, flavor: str, output: str, commands: List[str]):
        self.test_case.assertTrue(output and len(output) > 0, "expect console output")
        lines = output.splitlines()
        prefix = "(lldb) "

        for cmd in commands:
            cmd_stripped = cmd.lstrip("!?")
            for line in lines:
                if line.startswith(prefix) and cmd_stripped in line:
                    break
            else:
                self.test_case.fail(
                    f"Command '{flavor}' - '{cmd}' not found in output: {output}",
                )

    def get_modules(
        self, startModule: Optional[int] = None, moduleCount: Optional[int] = None
    ):
        args = ModulesArgs(startModule=startModule, moduleCount=moduleCount)
        response = self.request_and_respond(args)
        modules_dict = {module.name: module for module in response.body.modules}
        return modules_dict

    def get_threads(self) -> list[ThreadContext]:
        response = self.request_and_respond(ThreadsArgs())
        threads = response.body.threads
        t_threads = [ThreadContext(thread.id, self) for thread in threads]
        return t_threads

    def get_thread_context(self, thread_id: Optional[int]):
        thread_id = thread_id or self.stopped_thread_id
        return ThreadContext(thread_id, self)

    def current_thread(self) -> ThreadContext:
        """ThreadContext for the thread that last raised a StoppedEvent."""
        return ThreadContext(self.stopped_thread_id, self)

    def current_top_frame(self, thread_id: Optional[int]) -> FrameContext:
        """Top FrameContext of the currently stopped thread."""
        return self.get_thread_context(thread_id).top_frame()

    def get_completions(self, text: str, frameId: Optional[int]):
        def code_units(input: str) -> int:
            utf16_bytes = input.encode("utf-16-le")
            # one UTF16 codeunit = 2 bytes.
            return len(utf16_bytes) // 2

        com_args = CompletionsArgs(
            text=text, column=code_units(text) + 1, frameId=frameId
        )
        response = self.request_and_respond(com_args)
        return response.body.targets

    def get_exception_info(self, threadId: int):
        info_args = ExceptionInfoArgs(threadId=threadId)
        response = self.request_and_respond(info_args)
        return response.body

    def do_restart(self, arguments: Optional[Union[LaunchArgs, AttachArgs]] = None, /):
        restart_args = RestartArgs(arguments)
        return self.request_and_respond(restart_args)

    def send_disassemble(
        self,
        memoryReference: str,
        instructionOffset: int = -50,
        instructionCount: int = 200,
        resolveSymbols: bool = True,
    ):
        dis_args = DisassembleArgs(
            memoryReference=memoryReference,
            instructionOffset=instructionOffset,
            instructionCount=instructionCount,
            resolveSymbols=resolveSymbols,
        )
        return self.request_and_respond(dis_args).body.instructions

    def read_memory(
        self, memoryReference: str, count: int, offset: Optional[int] = None
    ):
        args = ReadMemoryArgs(
            memoryReference=memoryReference, offset=offset, count=count
        )
        handle = self.send_request(args)
        return self.get_response_or_error(handle)

    def write_memory(
        self,
        memoryReference: str,
        value: Optional[int] = None,
        *,
        offset: Optional[int] = None,
        allowPartial: bool = False,
    ):
        """Send a `writeMemory` request encoding `value` as little-endian bytes.

        This function accepts data in decimal and hexadecimal format,
        converts it to a Base64 string, and send it to the DAP,
        which expects Base64 encoded data.
        """
        if value is None:
            data = ""
        else:
            # (bit_length + 7 (rounding up to nearest byte) ) //8 = converts to bytes.
            byte_length = (value.bit_length() + 7) // 8
            val_bytes = value.to_bytes(byte_length, "little")
            data = base64.b64encode(val_bytes).decode()

        before_request = self.last_response()
        write_args = WriteMemoryArgs(
            memoryReference=memoryReference,
            data=data,
            offset=offset,
            allowPartial=allowPartial,
        )
        handle = self.send_request(write_args)
        response = self.get_response_or_error(handle)

        # Check we sent invalidated event.
        if response.success and self._init_args.supportsInvalidatedEvent:
            invalidated = self.wait_for_invalidated(after=before_request)
            self.test_case.assertEqual(invalidated.body.areas, ["all"])
        return response

    def do_disconnect(
        self, restart: Optional[bool] = None, terminateDebuggee: Optional[bool] = None
    ):
        args = DisconnectArgs(restart=restart, terminateDebuggee=terminateDebuggee)
        response = self.request_and_respond(args)

        self.test_case.assertTrue(response.success)
        return response
