"""
Test lldb-dap completions request
"""

# FIXME: remove when LLDB_MINIMUM_PYTHON_VERSION > 3.8
from __future__ import annotations

from typing import Optional
from dataclasses import dataclass

from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldb_dap.dap_types import (
    CompletionItem,
    LaunchArgs,
    StoppedReason,
    ThreadsArgs,
)
from lldb_dap.session_helpers import ThreadContext
from lldbsuite.test.lldbtest import line_number


@dataclass(frozen=True)
class Scenario:
    input: str
    expected: set[CompletionItem]
    not_expected: Optional[set[CompletionItem]] = None


session_completion = CompletionItem(
    label="session",
    detail="Commands controlling LLDB session.",
)
settings_completion = CompletionItem(
    label="settings",
    detail="Commands for managing LLDB settings.",
)
memory_completion = CompletionItem(
    label="memory",
    detail="Commands for operating on memory in the current target process.",
)
command_var_completion = CompletionItem(
    label="var",
    detail="Show variables for the current stack frame. Defaults to all arguments and local variables in scope. Names of argument, local, file static and file global variables can be specified.",
    length=3,
)
variable_var_completion = CompletionItem(label="var", detail="vector<baz> &", length=3)
variable_var1_completion = CompletionItem(label="var1", detail="int &")
variable_var2_completion = CompletionItem(label="var2", detail="int &")

str1_completion = CompletionItem(
    label="str1",
    detail="std::string &",
)


# Older version of libcxx produce slightly different typename strings for
# templates like vector.
# TODO: enable this back below.
# @skipIf(compiler="clang", compiler_version=["<", "16.0"])
class TestDAP_completions(DAPTestCaseBase):
    TEST_PROGRAM = r"""
#include <string>
#include <vector>

struct bar {
  int var1;
};

struct foo {
  int var1;
  bar *my_bar_pointer;
  bar my_bar_object;
  foo *next_foo;
};

struct baz {
  char c;
};

int fun(std::vector<baz> var) {
  return var.size(); // breakpoint 1
}

int main(int argc, char const *argv[]) {
  int var1 = 0;
  int var2 = 1;
  std::string str1 = "a";
  std::string str2 = "b";
  std::vector<baz> vec;
  fun(vec);
  bar bar1 = {2};
  bar *bar2 = &bar1;
  int ƒake_f = 200;
  foo foo1 = {3, &bar1, bar1, NULL};
  return 0; // breakpoint 2
}
"""

    def setUp(self):
        super().setUp()
        self.session = self.build_and_create_session()

    def verify_completions(self, case: Scenario, top_frame_id: Optional[int] = None):
        session = self.session
        completions = {
            comp for comp in session.get_completions(case.input, frameId=top_frame_id)
        }

        # handle expected completions
        for exp_comp in case.expected:
            self.assertIn(
                exp_comp, completions, f"\nCompletion for input: {case.input}"
            )

        # unexpected completions
        for not_exp_comp in case.not_expected or set():
            with self.subTest(f"Not expected completion : {not_exp_comp}"):
                self.assertNotIn(not_exp_comp, completions)

    def setup_debuggee(self):
        program = self.getBuildArtifact("a.out")
        source = "main.cpp"
        with self.session.configure(LaunchArgs(program)) as ctx:
            self.session.resolve_source_breakpoints(
                source,
                [
                    line_number(source, "// breakpoint 1"),
                    line_number(source, "// breakpoint 2"),
                ],
            )
        process_event = ctx.process_event()
        return self.session.verify_stopped_on_breakpoint(after=process_event)

    def verify_non_ascii_completion(self, alias_cmd: str):
        """Creates an command alias for the `next` command and
        verify if it has completion for the command and its help.

        It assumes we are in command mode in the repl.
        """
        self.session.evaluate(f"command alias {alias_cmd} next", context="repl")

        part = alias_cmd[:2]  # first two characters
        part_codeunits = len(part.encode("utf-16-le")) // 2

        next_detail = "Source level single step, stepping over calls.  Defaults to current thread unless specified."
        expected_item = CompletionItem(
            label=alias_cmd, detail=next_detail, length=part_codeunits
        )

        # complete the command
        self.verify_completions(Scenario(input=part, expected={expected_item}))
        # complete the help
        self.verify_completions(
            Scenario(input=f"help {part}", expected={expected_item})
        )

        # remove the alias
        self.session.evaluate(f"command unalias {alias_cmd}", context="repl")

    def test_command_completions(self):
        """
        Tests completion requests for lldb commands, within "repl-mode=command"
        """
        self.setup_debuggee()
        stop_event = self.session.continue_to_next_stop(
            exp_reason=StoppedReason.BREAKPOINT
        )

        self.session.evaluate("`lldb-dap repl-mode command", context="repl")
        # TODO: check the value of res.

        thread_ctx = self.session.get_thread_context(stop_event.body.threadId)
        top_frame_id = thread_ctx.top_frame().frame.id
        # Provides completion for top-level commands
        self.verify_completions(
            Scenario(
                input="se",
                expected={
                    session_completion.clone(length=2),
                    settings_completion.clone(length=2),
                },
            ),
            top_frame_id,
        )
        # Provides completions for sub-commands
        self.verify_completions(
            Scenario(
                input="memory ",
                expected={
                    CompletionItem(
                        label="read",
                        detail="Read from the memory of the current target process.",
                    ),
                    CompletionItem(
                        label="region",
                        detail="Get information on the memory region containing an address "
                        "in the current target process.\nIf this command is given an "
                        "<address-expression> once and then repeated without options, "
                        "it will try to print the memory region that follows the "
                        "previously printed region. The command can be repeated "
                        "until the end of the address range is reached.",
                    ),
                },
            ),
            top_frame_id,
        )

        # Provides completions for parameter values of commands
        self.verify_completions(
            Scenario(
                input="`log enable  ", expected={CompletionItem(label="gdb-remote")}
            ),
            top_frame_id,
        )

        # Also works if the escape prefix is used
        self.verify_completions(
            Scenario(input="`mem", expected={memory_completion.clone(length=3)}),
            top_frame_id,
        )

        self.verify_completions(
            Scenario(
                input="`",
                expected={session_completion, settings_completion, memory_completion},
            ),
            top_frame_id,
        )

        # Completes an incomplete quoted token
        self.verify_completions(
            Scenario(
                input='setting "se',
                expected={
                    CompletionItem(
                        label="set",
                        detail="Set the value of the specified debugger setting.",
                        length=3,
                    )
                },
            ),
            top_frame_id,
        )

        # Completes an incomplete quoted token
        self.verify_completions(
            Scenario(input="'mem", expected={memory_completion.clone(length=4)}),
            top_frame_id,
        )

        # Completes expressions with quotes inside
        self.verify_completions(
            Scenario(
                input='expr " "; typed',
                expected={CompletionItem(label="typedef", length=5)},
            ),
            top_frame_id,
        )

        # Provides completions for commands, but not variables
        self.verify_completions(
            Scenario(
                input="var",
                expected={command_var_completion},
                not_expected={variable_var_completion},
            ),
            top_frame_id,
        )

        # Completes partial completion
        self.verify_completions(
            Scenario(
                input="plugin list ar",
                expected={CompletionItem(label="architecture", length=2)},
            ),
            top_frame_id,
        )

        # Complete custom command with non ascii character.
        self.verify_non_ascii_completion("n€xt")  # 2 bytes £
        self.verify_non_ascii_completion("n£xt")  # 3 bytes €
        self.verify_non_ascii_completion("n💩xt")  # 4 bytes 💩
        self.verify_non_ascii_completion("√∂xt")  # start with non ascii
        self.verify_non_ascii_completion("one_seç")  # ends with non ascii

    # TODO FIx this function.
    def test_variable_completions(self):
        """
        Tests completion requests in "repl-mode=variable"
        """

        stop_event = self.setup_debuggee()
        thread_ctx = self.session.get_thread_context(stop_event.body.threadId)
        top_frame_id = thread_ctx.top_frame().frame.id
        session = self.session
        session.evaluate(
            "`lldb-dap repl-mode variable", context="repl", frameId=top_frame_id
        )

        # Provides completions for variables, but not command
        self.verify_completions(
            Scenario(
                input="var",
                expected={variable_var_completion},
                not_expected={command_var_completion},
            ),
            top_frame_id,
        )

        # We stopped inside `fun`, so we shouldn't see variables from main
        self.verify_completions(
            Scenario(
                input="var",
                expected={variable_var_completion},
                not_expected={
                    variable_var1_completion.clone(length=3),
                    variable_var2_completion.clone(length=3),
                },
            ),
            top_frame_id,
        )

        # We should see global keywords but not variables inside main
        self.verify_completions(
            Scenario(
                input="str",
                expected={CompletionItem(label="struct", length=3)},
                not_expected={str1_completion.clone(length=3)},
            ),
            top_frame_id,
        )

        stop_event = self.session.continue_to_next_stop()
        thread_ctx = self.session.get_thread_context(stop_event.body.threadId)
        top_frame_id = thread_ctx.top_frame().frame.id

        # We stopped in `main`, so we should see variables from main but
        # not from the other function
        self.verify_completions(
            Scenario(
                input="var",
                expected={
                    variable_var1_completion.clone(length=3),
                    variable_var2_completion.clone(length=3),
                },
                not_expected={
                    variable_var_completion.clone(length=3),
                },
            ),
            top_frame_id,
        )

        self.verify_completions(
            Scenario(
                input="str",
                expected={
                    CompletionItem(label="struct", length=3),
                    str1_completion.clone(length=3),
                },
            ),
            top_frame_id,
        )

        self.assertIsNotNone(self.session.get_completions("ƒ", top_frame_id))
        # Test utf8 after ascii.
        self.session.get_completions("mƒ", top_frame_id)

        # Completion also works for more complex expressions
        self.verify_completions(
            Scenario(
                input="foo1.v",
                expected={CompletionItem(label="foo1.var1", detail="int", length=6)},
            ),
            top_frame_id,
        )

        self.verify_completions(
            Scenario(
                input="foo1.my_bar_object.v",
                expected={
                    CompletionItem(
                        label="foo1.my_bar_object.var1", detail="int", length=20
                    )
                },
            ),
            top_frame_id,
        )

        self.verify_completions(
            Scenario(
                input="foo1.var1 + foo1.v",
                expected={CompletionItem(label="foo1.var1", detail="int", length=6)},
            ),
            top_frame_id,
        )

        self.verify_completions(
            Scenario(
                input="foo1.var1 + v",
                expected={CompletionItem(label="var1", detail="int &", length=1)},
            ),
            top_frame_id,
        )

        # should correctly handle spaces between objects and member operators
        self.verify_completions(
            Scenario(
                input="foo1 .v",
                expected={CompletionItem(label=".var1", detail="int", length=2)},
                not_expected={CompletionItem(label=".var2", detail="int", length=2)},
            ),
            top_frame_id,
        )

        self.verify_completions(
            Scenario(
                input="foo1 . v",
                expected={CompletionItem(label="var1", detail="int", length=1)},
                not_expected={CompletionItem(label="var2", detail="int", length=1)},
            ),
            top_frame_id,
        )

        # Even in variable mode, we can still use the escape prefix
        self.verify_completions(
            Scenario(input="`mem", expected={memory_completion.clone(length=3)}),
            top_frame_id,
        )

    def test_auto_completions(self):
        """
        Tests completion requests in "repl-mode=auto"
        """
        stop_event = self.setup_debuggee()
        session = self.session

        session.evaluate("`lldb-dap repl-mode auto", context="repl")

        thread_ctx = self.session.get_thread_context(stop_event.body.threadId)
        top_frame_id = thread_ctx.top_frame().frame.id

        # Stopped at breakpoint 1
        # 'var' variable is in scope, completions should not show any warning.
        # We check this at the end of the test.
        session.get_completions("var ", top_frame_id)
        stop_event = session.continue_to_next_stop(exp_reason=StoppedReason.BREAKPOINT)

        # We stopped in `main` function. Variables `var1` and `var2` are in scope.
        # Make sure, we offer all completions
        self.verify_completions(
            Scenario(
                input="va",
                expected={
                    command_var_completion.clone(length=2),
                    variable_var1_completion.clone(length=2),
                    variable_var2_completion.clone(length=2),
                },
            ),
            top_frame_id,
        )

        # If we are using the escape prefix, only commands are suggested, but no variables
        self.verify_completions(
            Scenario(
                input="`va",
                expected={
                    command_var_completion.clone(length=2),
                },
                not_expected={
                    variable_var1_completion.clone(length=2),
                    variable_var2_completion.clone(length=2),
                },
            ),
            top_frame_id,
        )

        # TODO: Note we are not checking the result because the `expression --` command adds an extra character
        # for non ascii variables.
        self.assertIsNotNone(session.get_completions("ƒ", top_frame_id))

        session.continue_to_exit()
        console_str = session.get_console()
        # we check in console to avoid waiting for output event.
        self.assertNotIn(
            "Expression 'var' is both an LLDB command and variable", console_str
        )
