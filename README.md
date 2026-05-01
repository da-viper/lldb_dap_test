# Proposed lldb_dap test framework

## Add more information on the proposed changes.

> NOTE: I have not tested it on a Windows computer yet (it should not make a
> difference), but I will do so before upstreaming. Most of the
> `@skipIfWindows` tests are uncommented.

Not all the tests are rewritten, just the ones I needed to verify a function
works correctly.
Will upstream as follows:

- The `lldb_dap` folder with some basic tests and one problematic test
  (possibly the modules event) to make sure it works correctly.
- Add new tests, grouped together, that work on all three platforms.
- Once all the new tests are added, remove the old test library and tests.

## Running tests

```bash
# Required: Set the path to your lldb-dap binary.
export DAP_ADAPTER_PATH=/path/to/lldb-dap

# Optional: override the default timeout for wait_for_*_events (seconds).
export DAP_TIMEOUT=100

# Optional: run lldb_dap in server mode for the tests.
export DAP_RUN_AS_SERVER=1

# Run a single test file.
uv run pytest tests/TestDAP_step.py -x

# Run a single test method (file.py::module::test_name).
uv run pytest tests/TestDAP_step.py::TestDAP_step::test_step

# Run in parallel (uses pytest-dist).
uv run pytest -n auto

# Or run without installing dependencies
python3 run_test TestLaunch, tests/TestDAP_step.py
```

> NOTE: The test is still using the built in unittest but pytest gives better
> errors and it's easier to run tests in parallel.
> the names of some classes may not be the best to describe what it does.
> feel free to suggest new ones.

Per-test artifacts (compiled binaries, adapter logs) are written under
`builds/<test_module>/<test_method>/`.

## Brief summary of what each class does

```
# The direction from a testcase to the adapter.
DAPTestCaseBase <-> DAPTestSession <-> Session <-> DAPConnection <-> Transport <-> lldb-dap
```

When writing a new test, you will not need to interact directly with most of
these classes (except `DAPTestSession` and the contexts; see below).

### DAPTestSession (`session_helpers.py`)

Inherits from `Session` and holds the current `unittest.TestCase` to expose
`assertXXX` helpers. Adds helpers for writing new tests, such as
`session.start_debug_session(launch_args)` and
`session.wait_for_event(after=stop_event)`. It does not hold any session
state. It will be used directly when writing any test.

- **`configure(LaunchArgs | AttachArgs)`** (still deciding if this is a good
  name) Context manager that scopes the initialize-sequence handshake. We
  can do something like:

  ```python
  with session.configure(LaunchArgs(program="/path/to/program")) as ctx:
      # On entering the context we send the:
      # - Initialize request
      # - Launch / Attach request
      # - And wait for the initialized event.

      # Here we have received the initialized event, and we can now set breakpoints.
      bp_id = session.resolve_function_breakpoints(["main"])  # waits until the breakpoint is resolved

      # Only does the send and get request and response.
      bp_response = session.set_source_breakpoints("main.cpp", [10, 20])

      # Leaving the context, we now do configurationDone,
      # get the launch/attach response, and a process event.

  # Outside the context we can now use the process event or launch response.
  process_event = ctx.process_event()
  stop_event = session.verify_stopped_on_entry(after=process_event)
  ```

- **Launch using config**: still debating if it is better than the context
  method above. Both are in the codebase.

  ```python
  # You can only add pending_XXXX_breakpoints before the session is initialized;
  # if not, it will throw an error.
  session.add_pending_function_breakpoints(["main"])
  session.add_pending_source_breakpoints("main.cpp", [10, 20])

  process_event, bp_id = session.launch_using_config(LaunchArgs(program="/path/to/program"))
  # bp_id contains resolved function and source breakpoints added through
  # add_pending_XXXX. It is less flexible than the context method.
  ```

- **Breakpoint helpers**: `set_source_breakpoints`,
  `set_function_breakpoints`, plus `resolve_*` variants that wait for each
  breakpoint to be verified before returning IDs.

- **Stop assertions**: `verify_stopped_on_breakpoint`,
  `verify_stopped_on_entry`, `continue_to_next_stop`, `continue_to_exit`.

- **Stop-bound contexts**:

  - `ThreadContext.frames()` returns a list of `FrameContext`.
  - `FrameContext.scopes()` returns a list of `ScopeContext`. The frame also
    exposes `locals` / `globals` / `registers` properties.
  - `ScopeContext.variables()` returns a list of `VariableContext`.
  - `VariableContext.children()` returns a list of `VariableContext`.
    Subscripting (`scope["x"]`) returns a `VariableContext`.

  This allows for:

  ```python
  stop_event = session.verify_stopped_on_breakpoint(after=process_event)
  thread_ctx = session.get_thread_ctx(stop_event.body.threadId)
  # We can now get information on the scopes, frames, and variables.
  top_frame = thread_ctx.top_frame()
  # evaluate request
  top_frame.evaluate("some_value", context="repl")

  # scopes
  all_scopes = top_frame.scopes()  # calls scope request
  local_scope = top_frame.locals

  local_variables = local_scope.variables()
  # Or using a valueFormat
  formatted_local_variables = local_scope.with_format(hex=True).variables()

  # view variables
  some_class = top_frame.locals["some_class"]
  some_class.has_children
  some_class.children()
  member = some_class["member"]
  # member.value_as_int, member.name, etc.
  ```

  All four classes are tied to a `stop_generation`. See more on stop
  generation below.

### Session (`client.py`)

Handles sending requests and receiving responses and events from the
connection. It handles things like `RunInTerminal` and the new
`CapabilitiesEvent`. It should be able to handle creating child sessions
in the future. It owns the `DAPConnection` and the `EventHistory`.

### DAPConnection (`utils.py`)

Encodes the DAP format (`Content-Length: <n>\r\n\r\n`) and forwards
errors, responses, and events to the session. It maps every request
sequence to a `concurrent.futures.Future`. We can get the future's
response or exception using `get_response`. It also validates that the
request matches the response, and that there is only one response per
request. We can create multiple connections (in server mode) if needed.

### Transport (`utils.py`)

A `Transport` is an interface for how the DAP connection connects to
`lldb-dap` (either stdio or socket). `DebugAdapter.create_transport()`
picks between them based on whether the adapter was started in server
mode.

## Other helpers

#### EventHistory (`utils.py`)

Every event the debug adapter sends is recorded here by the read thread,
in the order it arrived. Tests don't read the log directly; they call one
of the `wait_for_*` methods, which block until a matching event has been
recorded (or return immediately if one already has).

Each wait is scoped to "events after some earlier message". A test
records some earlier event or response, performs an action, then asks for
the next event of a given kind that came after it. This means the wait
still works even if the event arrives before the test gets around to
asking for it. The internal log already holds it, and the wait resolves right away
instead of timing out.

Example:
Wait for a stop after stepping, without racing the adapter:

```python
step_resp = session.step_in(thread_id=1)
# The StoppedEvent may arrive before or after this line; we do
# not care, because the wait looks for events after step_resp.
stopped = history.wait_for_event(StoppedEvent, after=step_resp)
```

#### ResponseHandle (`session.py`)

`ResponseHandle[AnyResponse]` It is generic over the expected Response
`Session.send_request`. It is the typed receipt for a request that has
been sent but not yet answered, carrying two things:

In other words, the handle lets the test pair "I sent this request" with
"now give me its response" safely across a concurrent read thread —
without having to carry the `seq` around by hand or lose the expected
type.

```python
handle = session.send_request(SetBreakpointsArgs(...))
# do other work, set other requests, wait for events, etc.

response = session.get_response(handle)  # returns the typed response
# OR
response = handle.get_response()
# response is (SetBreakpointResponse)
```

`request_and_respond` is the common shortcut that does
`send_request` → `get_response` in one call. Callers only touch a
`ResponseHandle` directly when they want to send the request now and
collect the response later (for example, To issue a request whose answer
arrives after an event they also want to observe).

#### stop_generation

An integer that is incremented any time the session resumes or terminates
(such as Continue or StepOut), to ensure tests are not using object
references (such as `frameId` or `variablesReference`) that are no longer
valid once the stop ends. This is enforced by the stop-bound contexts
(`FrameContext`, `ScopeContext`, and `VariableContext`).

> NOTE: this does not apply to `ThreadContext`, as it does not have a
> limited lifetime.

This catches the "I held a `frameId` or `var_ref` across a continue and
it now points at a different stack frame" class of bug.

## dap_types.py

Contains code for serializing/deserializing dictionaries to and from
frozen DAP dataclasses.

## Quick example

```python
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase, line_number
from lldb_dap.dap_types import LaunchArgs


class TestMyFeature(DAPTestCaseBase):
    # It will not be done like this when upstreamed. It will use the
    # normal self.build().
    TEST_PROGRAM = r"""
    int main() {
      int x = 1;
      return x; // breakpoint here
    }
    """

    def test_value_of_x(self):
        program = self.create_test_program_with_name("main.cpp")
        source = self.getSourcePath("main.cpp")
        bp_line = line_number(source, "// breakpoint here")
        session = self.session

        # Startup handshake:
        # =========== Possible Launch sequences ==========
        # Use the configure method.
        # initial breakpoints set inside the `with` block.
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [bp_line])
        process_event = ctx.process_event()

        # (still debating which one to use, depends on which one is easier to write test with)
        # Or use the pending style
        # breakpoints set before launch_using_config.
        session.add_pending_source_breakpoints(source, [bp_line])
        process_event, _ = session.launch_using_config(Launch(program))
        # =========== Launch Sequence ends ==========

        session.verify_stopped_on_breakpoint(after=process_event)

        x = session.current_frame().locals["x"]
        self.assertEqual(x.value, "1")
        self.assertEqual(x.type, "int")

        session.continue_to_exit()
```
