"""
Test lldb-dap progress events.
"""

import re
from typing import List, Optional, Union

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.tools.lldb_dap.dap_types import (
    LaunchArgs,
    ProgressEndEvent,
    ProgressStartEvent,
    ProgressUpdateEvent,
)
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.tools.lldb_dap.session_helpers import DAPTestSession

_ProgressEvent = Union[ProgressStartEvent, ProgressUpdateEvent, ProgressEndEvent]


class TestDAP_progress(DAPTestCaseBase):
    TEST_PROGRAM = r"""
int main() {
  const char *ptr = "unused";
  // break here
  return 0;
}
"""
    PROGRESS_EMITTER = r"""
import inspect
import optparse
import shlex
import sys
import time

import lldb


class ProgressTesterCommand:
    program = "test-progress"

    @classmethod
    def register_lldb_command(cls, debugger, module_name):
        parser = cls.create_options()
        cls.__doc__ = parser.format_help()
        # Add any commands contained in this module to LLDB
        command = "command script add -c %s.%s %s" % (
            module_name,
            cls.__name__,
            cls.program,
        )
        debugger.HandleCommand(command)
        print(
            'The "{0}" command has been installed, type "help {0}" or "{0} '
            '--help" for detailed help.'.format(cls.program)
        )

    @classmethod
    def create_options(cls):
        usage = "usage: %prog [options]"
        description = "SBProgress testing tool"
        # Opt parse is deprecated, but leaving this the way it is because it allows help formating
        # Additionally all our commands use optparse right now, ideally we migrate them all in one go.
        parser = optparse.OptionParser(
            description=description, prog=cls.program, usage=usage
        )

        parser.add_option(
            "--total",
            dest="total",
            help="Total items in this progress object. When this option is not specified, this will be an indeterminate progress.",
            type="int",
            default=None,
        )

        parser.add_option(
            "--seconds",
            dest="seconds",
            help="Total number of seconds to wait between increments",
            type="int",
        )

        parser.add_option(
            "--no-details",
            dest="no_details",
            help="Do not display details",
            action="store_true",
            default=False,
        )

        return parser

    def get_short_help(self):
        return "Progress Tester"

    def get_long_help(self):
        return self.help_string

    def __init__(self, debugger, unused):
        self.parser = self.create_options()
        self.help_string = self.parser.format_help()

    def __call__(self, debugger, command, exe_ctx, result):
        command_args = shlex.split(command)
        try:
            (cmd_options, args) = self.parser.parse_args(command_args)
        except:
            result.SetError("option parsing failed")
            return

        total = cmd_options.total
        if total is None:
            progress = lldb.SBProgress(
                "Progress tester", "Initial Indeterminate Detail", debugger
            )
        else:
            progress = lldb.SBProgress(
                "Progress tester", "Initial Detail", total, debugger
            )
        # Check to see if total is set to None to indicate an indeterminate
        # progress then default to 3 steps.
        with progress:
            if total is None:
                total = 3

            for i in range(1, total):
                if cmd_options.no_details:
                    progress.Increment(1)
                else:
                    progress.Increment(1, f"Step {i}")
                time.sleep(cmd_options.seconds)


def __lldb_init_module(debugger, dict):
    # Register all classes that have a register_lldb_command method
    for _name, cls in inspect.getmembers(sys.modules[__name__]):
        if inspect.isclass(cls) and callable(
            getattr(cls, "register_lldb_command", None)
        ):
            cls.register_lldb_command(debugger, __name__)
"""

    def build(self, filename: Optional[str] = None):
        super().build(filename)
        self.create_file(self.PROGRESS_EMITTER, "Progress_emitter.py")

    def collect_progress_events(self, session: DAPTestSession, *, after):
        """Collect ProgressXXXX events between `after` and the next ProgressEndEvent."""
        events: List[_ProgressEvent] = []

        def matches_progress_end(evt) -> bool:
            events.append(evt)
            return isinstance(evt, ProgressEndEvent)

        session.wait_for_any_event(
            (ProgressStartEvent, ProgressUpdateEvent, ProgressEndEvent),
            after=after,
            until=matches_progress_end,
            timeout_msg="Collecting ProgressXXXXEvents until ProgressEndEvent",
        )
        return events

    def verify_progress_events(
        self,
        events: List[_ProgressEvent],
        *,
        expected_title: str,
        expected_message: Optional[str] = None,
        expected_message_regex: Optional[str] = None,
        expected_not_in_message: Optional[str] = None,
        only_verify_first_update: bool = False,
    ):
        # A progress group is shaped: [ProgressStart, ProgressUpdate*, ProgressEnd].
        self.assertGreaterEqual(
            len(events), 3, "expected at least start + one update + end"
        )
        [start, *updates, end] = events

        self.assertIsInstance(start, ProgressStartEvent)
        self.assertIn(expected_title, start.body.title)
        self.assertIsInstance(end, ProgressEndEvent)

        for i, update in enumerate(updates):
            self.assertIsInstance(update, ProgressUpdateEvent)
            if only_verify_first_update and i > 0:
                break
            message = update.body.message or ""
            if expected_message is not None:
                self.assertIn(expected_message, message)
            if expected_message_regex is not None:
                self.assertTrue(re.match(expected_message_regex, message))
            if expected_not_in_message is not None:
                self.assertNotIn(expected_not_in_message, message)

    @skipIfWindows
    def test_progress(self):
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        process_event = session.launch(LaunchArgs(program, stopOnEntry=True))
        stopped = session.verify_stopped_on_entry(after=process_event)
        progress_emitter = self.getSourcePath("Progress_emitter.py")
        session.evaluate(f"`command script import {progress_emitter}", context="repl")

        # Test details.
        session.evaluate("`test-progress --total 3 --seconds 1", context="repl")
        events = self.collect_progress_events(session, after=stopped)
        progress_end = events[-1]
        self.verify_progress_events(
            events,
            expected_title="Progress tester",
            expected_not_in_message="Progress tester",
        )

        # Test no details.
        session.evaluate("`test-progress --total 3 --seconds 1 --no-details")
        events = self.collect_progress_events(session, after=progress_end)
        progress_end = events[-1]
        self.verify_progress_events(
            events,
            expected_title="Progress tester",
            expected_message="Initial Detail",
        )

        # Test details indeterminate.
        session.evaluate("`test-progress --seconds 1", context="repl")
        events = self.collect_progress_events(session, after=progress_end)
        progress_end = events[-1]
        self.verify_progress_events(
            events,
            expected_title="Progress tester: Initial Indeterminate Detail",
            expected_message_regex=r"Step [0-9]+",
        )

        # Test no details indeterminate.
        session.evaluate("`test-progress --seconds 1 --no-details", context="repl")
        events = self.collect_progress_events(session, after=progress_end)
        self.verify_progress_events(
            events,
            expected_title="Progress tester: Initial Indeterminate Detail",
            expected_message="Initial Indeterminate Detail",
            only_verify_first_update=True,
        )
