import threading
import unittest
from typing import List, Union

from lldbsuite.test.tools.lldb_dap.types import (
    CapabilitiesEvent,
    DAPError,
    Event,
    ExitedEvent,
    InitializedEvent,
    ModuleEvent,
    OutputEvent,
    ProcessEvent,
    ProgressEndEvent,
    TerminatedEvent,
)
from lldbsuite.test.tools.lldb_dap.utils import EventHistory


class TestDAPUtils_EventHistory(unittest.TestCase):
    """
    This test suite verifies the behavior of EventHistory, including event ordering validation,
    querying specific events, handling closed histories, applying custom filtering conditions,
    and managing timeouts during asynchronous event additions.
    """

    def generate_events(self) -> List[Event]:
        """Generates the default events that is used in tests."""
        # fmt: off
        raw_events = [
            {"body": {"category": "console", "output": "Running preInitCommands:\n"}, "event": "output", "seq": 1, "type": "event"},
            {"body": {"category": "console", "output": "(lldb) log enable lldb event -T -f dap_event.log\n"}, "event": "output", "seq": 3, "type": "event"},
            {"body": {"category": "console", "output": "To get started with the debug console try \"<variable>\", \"<lldb-cmd>\" or \"help [<lldb-cmd>]\"\r\n"}, "event": "output", "seq": 4, "type": "event"},
            {"body": {"category": "console", "output": "For more information visit https://lldb.llvm.org/use/lldbdap.html#debug-console.\r\n"}, "event": "output", "seq": 5, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4e6e000", "debugInfoSize": "563.1KB", "id": "A55BBBD8-5660-8820-2DBB-60DA08A95C6B-7697E8EE", "name": "ld-linux-x86-64.so.2", "path": "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2", "symbolFilePath": "/usr/lib/debug/.build-id/a5/5bbbd8566088202dbb60da08a95c6b7697e8ee.debug", "symbolStatus": "Symbols loaded."}, "reason": "new"}, "event": "module", "seq": 6, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4e6c000", "id": "E500AEFD-F104-2A72-8C7D-8390BFD2A311-02F8A183", "name": "[vdso]", "path": "[vdso]", "symbolStatus": "Symbols not found."}, "reason": "new"}, "event": "module", "seq": 7, "type": "event"},
            {"body": {"module": {"addressRange": "0x5fd98276c000", "debugInfoSize": "1.1KB", "id": "2C18BEA2-9D64-2123-5FBA-0344D06183D9-E7DCA074", "name": "a.out", "path": "/home/buildbot/workspace/a.out", "symbolFilePath": "/home/buildbot/workspace/a.out", "symbolStatus": "Symbols loaded."}, "reason": "new"}, "event": "module", "seq": 8, "type": "event"},
            {"body": {}, "event": "initialized", "seq": 9, "type": "event"},
            {"body": {"breakpoint": {"column": 3, "id": 1, "instructionReference": "0x5FD98276D191", "line": 13, "verified": True}, "reason": "changed"}, "event": "breakpoint", "seq": 11, "type": "event"},
            {"body": {"breakpoint": {"column": 3, "id": 2, "instructionReference": "0x5FD98276D1CD", "line": 18, "verified": True}, "reason": "changed"}, "event": "breakpoint", "seq": 12, "type": "event"},
            {"body": {"breakpoint": {"column": 3, "id": 3, "instructionReference": "0x5FD98276D1E4", "line": 20, "verified": True}, "reason": "changed"}, "event": "breakpoint", "seq": 13, "type": "event"},
            {"body": {"capabilities": {"supportsModuleSymbolsRequest": False, "supportsRestartRequest": False, "supportsStepInTargetsRequest": True}}, "event": "capabilities", "seq": 14, "type": "event"},
            {"body": {"category": "console", "output": "Executable binary set to '/home/buildbot/workspace/a.out' (x86_64-unknown-linux-gnu).\r\n"}, "event": "output", "seq": 15, "type": "event"},
            {"body": {"category": "console", "output": "Attached to process 2961472.\r\n"}, "event": "output", "seq": 16, "type": "event"},
            {"body": {"isLocalProcess": True, "name": "/home/buildbot/workspace/a.out", "pointerSize": 64, "startMethod": "launch", "systemProcessId": 2961472}, "event": "process", "seq": 17, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4d3e000", "debugInfoSize": "936.7KB", "id": "0558EEC1-E2C0-3F68-8CF3-83E73579DEF7-863A61D0", "name": "libm.so.6", "path": "/lib/x86_64-linux-gnu/libm.so.6", "symbolFilePath": "/usr/lib/debug/.build-id/05/58eec1e2c03f688cf383e73579def7863a61d0.debug", "symbolStatus": "Symbols loaded."}, "reason": "new"}, "event": "module", "seq": 21, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4600000", "debugInfoSize": "3.6MB", "id": "A5B27DB7-EF30-36C1-DACF-2E4DDC2E0527-67129439", "name": "libc.so.6", "path": "/lib/x86_64-linux-gnu/libc.so.6", "symbolFilePath": "/usr/lib/debug/.build-id/a5/b27db7ef3036c1dacf2e4ddc2e052767129439.debug", "symbolStatus": "Symbols loaded."}, "reason": "new"}, "event": "module", "seq": 22, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4a00000", "id": "280F658F-43AA-E7A7-F92B-BA6EC4C5D96B-C2B53A7A", "name": "libstdc++.so.6", "path": "/lib/x86_64-linux-gnu/libstdc++.so.6", "symbolStatus": "Symbols not found."}, "reason": "new"}, "event": "module", "seq": 23, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4d11000", "id": "183187C1-CD58-CFF0-9C2A-25539EEB6AE6-14C67F19", "name": "libgcc_s.so.1", "path": "/lib/x86_64-linux-gnu/libgcc_s.so.1", "symbolStatus": "Symbols not found."}, "reason": "new"}, "event": "module", "seq": 24, "type": "event"},
            {"body": {"allThreadsStopped": True, "description": "breakpoint 1.1", "hitBreakpointIds": [1], "reason": "breakpoint", "text": "breakpoint 1.1", "threadId": 2961472}, "event": "stopped", "seq": 25, "type": "event"},
            {"body": {"allThreadsContinued": True, "threadId": 2961472}, "event": "continued", "seq": 27, "type": "event"},
            {"body": {"category": "stdout", "output": "before dlopen\r\n"}, "event": "output", "seq": 28, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4e5f000", "debugInfoSize": "782B", "id": "F71ED270-47EF-5421-FD13-E6B6FAADED6B-3BC4D52D", "name": "libother.so", "path": "/home/buildbot/workspace/libother.so", "symbolFilePath": "/home/buildbot/workspace/libother.so", "symbolStatus": "Symbols loaded."}, "reason": "new"}, "event": "module", "seq": 29, "type": "event"},
            {"body": {"allThreadsStopped": True, "description": "breakpoint 2.1", "hitBreakpointIds": [2], "reason": "breakpoint", "text": "breakpoint 2.1", "threadId": 2961472}, "event": "stopped", "seq": 30, "type": "event"},
            {"body": {"allThreadsContinued": True, "threadId": 2961472}, "event": "continued", "seq": 32, "type": "event"},
            {"body": {"category": "stdout", "output": "before dlclose\r\n"}, "event": "output", "seq": 33, "type": "event"},
            {"body": {"module": {"id": "F71ED270-47EF-5421-FD13-E6B6FAADED6B-3BC4D52D", "name": ""}, "reason": "removed"}, "event": "module", "seq": 34, "type": "event"},
            {"body": {"breakpoint": {"column": 3, "id": 1, "instructionReference": "0x5FD98276D191", "line": 13, "verified": True}, "reason": "changed"}, "event": "breakpoint", "seq": 35, "type": "event"},
            {"body": {"breakpoint": {"column": 3, "id": 2, "instructionReference": "0x5FD98276D1CD", "line": 18, "verified": True}, "reason": "changed"}, "event": "breakpoint", "seq": 36, "type": "event"},
            {"body": {"breakpoint": {"column": 3, "id": 3, "instructionReference": "0x5FD98276D1E4", "line": 20, "verified": True}, "reason": "changed"}, "event": "breakpoint", "seq": 37, "type": "event"},
            {"body": {"allThreadsStopped": True, "description": "breakpoint 3.1", "hitBreakpointIds": [3], "reason": "breakpoint", "text": "breakpoint 3.1", "threadId": 2961472}, "event": "stopped", "seq": 41, "type": "event"},
            {"body": {"allThreadsContinued": True, "threadId": 2961472}, "event": "continued", "seq": 43, "type": "event"},
            {"body": {"category": "stdout", "output": "GOT TOKEN 3200"}, "event": "output", "seq": 44, "type": "event"},
            {"body": {"category": "console", "output": "Process 2961472 exited with status = 0 (0x00000000) \n"}, "event": "output", "seq": 45, "type": "event"},
            {"body": {}, "event": "terminated", "seq": 46, "type": "event"},
            {"body": {"exitCode": 0}, "event": "exited", "seq": 47, "type": "event"},
        ]
        # fmt: on
        events = [Event.from_json(raw_event) for raw_event in raw_events]
        return events

    def populate_history(self, history: EventHistory):
        for event in self.generate_events():
            history.record(event)

    def test_history_order(self):
        """Test that events added to EventHistory are in sequential order"""

        history = EventHistory(timeout=10)
        event_1 = Event.from_json(
            {
                "body": {
                    "category": "console",
                    "output": "Running preInitCommands:\n",
                },
                "event": "output",
                "seq": 2,
                "type": "event",
            }
        )
        event_2 = Event.from_json(
            {
                "body": {
                    "category": "console",
                    "output": "(lldb) log enable lldb process",
                },
                "event": "output",
                "seq": 1,
                "type": "event",
            }
        )

        history.record(event_1)
        with self.assertRaises(DAPError) as ctx:
            history.record(event_2)

        self.assertIn("older than last event", str(ctx.exception))

    def test_wait_for_X_event_on_history_closed(self):
        """Tests `wait_for_first_event`, `wait_for_event` and `wait_for_any_event` when the history is closed.

        It should return a DAPError (HistoryClosed) instead of waiting for new events if the
        history is closed and the requested event does not already exist in the history.
        """
        history = EventHistory(timeout=10)
        self.populate_history(history)

        # We only intend on working on existing events.
        # so we don't get a Timeout error.
        history.close()

        init_event = history.wait_for_earliest_event(InitializedEvent)
        self.assertEqual(init_event.seq, 9)
        self.assertIsInstance(init_event, InitializedEvent)
        self.assertEqual(init_event.type, "event")

        cap_event = history.wait_for_event(CapabilitiesEvent, after=init_event)
        self.assertGreater(cap_event.seq, init_event.seq)
        self.assertIsInstance(cap_event, CapabilitiesEvent)

        # There is only one capabilitiesEvent in the history.
        with self.assertRaises(DAPError):
            history.wait_for_event(CapabilitiesEvent, after=cap_event)

        # There is no progressEndEvent in history.
        with self.assertRaises(DAPError):
            history.wait_for_earliest_event(ProgressEndEvent)

        # Must wait for at least one event.
        with self.assertRaises(AssertionError):
            history.wait_for_any_event((), after=cap_event)

        # Test wait_for_any_event.
        # Wait for_any_event should return the first seen event that in in the tuple
        any_event = history.wait_for_any_event(
            (ProcessEvent, OutputEvent, ModuleEvent, TerminatedEvent), after=cap_event
        )
        # We should see the output event first.
        self.assertIsInstance(any_event, OutputEvent)

        any_event = history.wait_for_any_event(
            (ModuleEvent, TerminatedEvent), after=cap_event
        )

        # We should see the ModuleEvent event first.
        self.assertIsInstance(any_event, ModuleEvent)

    def test_wait_for_X_event_until_Y_condition(self):
        """
        Tests the `until` parameter in wait_for_XXXX methods.

        Verifies that `wait_for_event` and `wait_for_any_event` continue scanning
        through matching event types until the provided condition function returns True.
        or throws an error.
        """
        history = EventHistory(timeout=10)
        self.populate_history(history)
        history.close()

        start_event = history.wait_for_earliest_event(OutputEvent)
        self.assertEqual(start_event.seq, 1)
        self.assertIsInstance(start_event, OutputEvent)
        self.assertEqual(start_event.body.output, "Running preInitCommands:\n")

        # Test wait_for_event_until success.
        def has_got_token(event: OutputEvent):
            return "GOT TOKEN" in event.body.output

        output_event = history.wait_for_event(
            OutputEvent, after=start_event, until=has_got_token
        )
        self.assertEqual(output_event.seq, 44)
        self.assertIsInstance(output_event, OutputEvent)
        self.assertIn("GOT TOKEN", output_event.body.output)

        def sdl3_module_loaded(event: ModuleEvent):
            module_is_sdl = event.body.module.name == "sdl3"
            is_new_module = event.body.reason == "new"

            return module_is_sdl and is_new_module

        # Test wait_for_event_until failure.
        # There is no sdl3 module in the event history.
        with self.assertRaises(DAPError):
            history.wait_for_event(
                ModuleEvent, after=start_event, until=sdl3_module_loaded
            )

        # Test wait_for_any_event.
        def sdl3_module_loaded_or_process_exited(event):
            if isinstance(event, ModuleEvent):
                return sdl3_module_loaded(event)

            return True

        seen_event = history.wait_for_any_event(
            (ModuleEvent, ExitedEvent),
            after=start_event,
            until=sdl3_module_loaded_or_process_exited,
        )

        self.assertEqual(seen_event.seq, 47)
        self.assertIsInstance(seen_event, ExitedEvent)
        self.assertEqual(seen_event.body.exitCode, 0)  # type: ignore

    def test_wait_for_X_event_with_timeout(self):
        """Tests the timeout functionality when waiting for events.

        Verifies that a TimeoutError is raised if the expected event does not
        arrive within the specified timeout. Also ensures that the wait methods
        successfully block and retrieve events added asynchronously by another thread
        before the timeout expires.
        """
        history = EventHistory(timeout=10)
        self.populate_history(history)

        delayed_append = threading.Event()
        delayed_append.clear()

        new_cap_events = [
            Event.from_json(
                {
                    "body": {"capabilities": {"supportsModulesRequest": True}},
                    "event": "capabilities",
                    "seq": 50,
                    "type": "event",
                }
            ),
            Event.from_json(
                {
                    "body": {"capabilities": {"supportsRestartRequest": True}},
                    "event": "capabilities",
                    "seq": 52,
                    "type": "event",
                }
            ),
        ]

        def add_delayed_events(events: List[Event]):
            delayed_append.wait()
            for event in events:
                history.record(event)

        event_thread = threading.Thread(
            target=add_delayed_events, args=[new_cap_events]
        )
        event_thread.start()

        try:
            exited_event = history.wait_for_earliest_event(ExitedEvent)
            self.assertEqual(exited_event.seq, 47)
            self.assertEqual(exited_event.body.exitCode, 0)

            def supports_restart_request(event: CapabilitiesEvent):
                return event.body.capabilities.supportsRestartRequest == True

            # No new CapabilitiesEvents have been added after exited event, so this should time out.
            with self.assertRaises(TimeoutError):
                history.wait_for_event(
                    CapabilitiesEvent,
                    after=exited_event,
                    until=supports_restart_request,
                    timeout=0.05,
                )

            # Unblock and Sync with the event thread.
            delayed_append.set()
            seen_event = history.wait_for_event(
                CapabilitiesEvent,
                after=exited_event,
                until=supports_restart_request,
                timeout=10,
            )

            # The supportsModuleRequest CapabilitiesEvent should be ignored.
            self.assertEqual(seen_event.seq, 52)
            self.assertIsInstance(seen_event, CapabilitiesEvent)
            self.assertTrue(seen_event.body.capabilities.supportsRestartRequest)
        finally:
            delayed_append.set()
            event_thread.join()
