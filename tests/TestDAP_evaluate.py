"""
Test lldb-dap evaluate request
"""

import re
from typing import Optional

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.dap_types import (
    ErrorResponse,
    EvaluateContext,
    LaunchArgs,
    ValueFormat,
)
from lldbsuite.test.tools.lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.tools.lldb_dap.session_helpers import ExpectEval


class TestDAP_evaluate(DAPTestCaseBase):
    TEST_PROGRAM = r"""#include "foo.h"

#include <cstdint>
#include <map>
#include <vector>

static int static_int = 42;

int non_static_int = 43;

int a_function(int list) {
  return list; // breakpoint 3
}

struct my_struct {
  int foo;
};

int main(int argc, char const *argv[]) {
  my_struct struct1 = {15};
  my_struct *struct2 = new my_struct{16};
  my_struct *struct3 = nullptr;
  int var1 = 20;
  int var2 = 21;
  int var3 = static_int; // breakpoint 1
  {
    int non_static_int = 10;
    int var2 = 2;
    int var3 = non_static_int; // breakpoint 2
  }
  a_function(var3);
  foo_func();

  std::vector<int> my_vec;
  my_vec.push_back(1);
  my_vec.push_back(2);
  my_vec.push_back(3); // breakpoint 4

  std::map<int, int> my_map;
  my_map[1] = 2;
  my_map[2] = 3;
  my_map[3] = 4; // breakpoint 5

  std::vector<bool> my_bool_vec;
  my_bool_vec.push_back(true);
  my_bool_vec.push_back(false); // breakpoint 6
  my_bool_vec.push_back(true);  // breakpoint 7

  uint8_t my_ints[] = {5, 10, 15, 20, 25, 30};
  long my_longs[] = {5, 6, 7};
  return 0; // breakpoint 8
}
"""
    FOO_CPP = r"""#include "foo.h"

int foo_func() { return 43; }

int foo_var = 44;
"""
    FOO_H = """int foo_func();

extern int foo_var;
"""

    def build(self, filename=None):
        self.create_file(self.FOO_CPP, "foo.cpp")
        self.create_file(self.FOO_H, "foo.h")
        # Compile both translation units into a.out.
        main_path = self.create_file(self.TEST_PROGRAM, "main.cpp")
        foo_path = self.getSourcePath("foo.cpp")
        self.run_command(
            [
                "/usr/bin/clang++",
                "-g",
                "-o",
                self.getBuildArtifact("a.out"),
                main_path,
                foo_path,
            ]
        )

    context: Optional[EvaluateContext]

    def _frame_id(self, frame_index: Optional[int]):
        if frame_index is None:
            return None
        thread_ctx = self._session.thread_context_from(self._session.stopped_thread_id)
        frame = thread_ctx.frames(levels=frame_index + 1)[frame_index]
        return frame.id

    def assertEvaluate(
        self,
        expression,
        matches,
        *,
        frame_index: Optional[int] = 0,
        is_hex: bool = False,
        **expect_kwargs,
    ):
        # Defaults mirror the previous wrapper: assert no varref, assert memref.
        expect_kwargs.setdefault("has_mem_ref", True)
        pending = self._session.do_evaluate(
            expression,
            frameId=self._frame_id(frame_index),
            context=self.context,
            format=ValueFormat(hex=True) if is_hex else None,
        )
        result = pending.result(f"failed to evaluate {expression!r}")
        self._session.verify_evaluate(
            result.body, ExpectEval(matches=matches, **expect_kwargs)
        )

    def assertEvaluateFailure(self, expression):
        response = self._session.do_evaluate(
            expression, context=self.context
        ).result_or_error()
        # An error reported as a successful response with an "error: ..." result
        # also counts as a failure (lldb sometimes returns evaluation errors
        # this way).
        if not isinstance(response, ErrorResponse) and response.body.result.startswith(
            "error:"
        ):
            return
        self.assertIsInstance(
            response,
            ErrorResponse,
            f"Expression:'{expression}' should fail in {self.context} context, got {response!r}",
        )

    def isResultExpandedDescription(self):
        return self.context == "repl"

    def isResultShortDescription(self):
        return self.context == "clipboard"

    def isExpressionParsedExpected(self):
        return self.context != "hover"

    def run_test_evaluate_expressions(
        self,
        context: Optional[EvaluateContext] = None,
        enableAutoVariableSummaries: bool = False,
    ):
        """Tests the evaluate expression request at different breakpoints."""
        self.context = context
        program = self.getBuildArtifact("a.out")
        self._session = self.build_and_create_session()
        source = "main.cpp"

        launch_args = LaunchArgs(
            program=program, enableAutoVariableSummaries=enableAutoVariableSummaries
        )
        with self._session.configure(launch_args) as ctx:
            breakpoint_lines = [
                line_number(source, f"// breakpoint {i}") for i in range(1, 9)
            ]
            breakpoint_ids = self._session.resolve_source_breakpoints(
                source, breakpoint_lines
            )

        self.assertEqual(
            len(breakpoint_ids),
            len(breakpoint_lines),
            "Did not resolve all the breakpoints.",
        )
        bp1, bp2, bp3, bp4, bp5, bp6, bp7, bp8 = breakpoint_ids

        self._session.verify_stopped_on_breakpoint(bp1, after=ctx.process_event)

        # Expressions at breakpoint 1, which is in main.
        self.assertEvaluate("var1", "20", type="int")
        # Empty expression should equate to the previous expression.
        if context == "repl":
            self.assertEvaluate("", "20")
        else:
            self.assertEvaluateFailure("")
        self.assertEvaluate("var2", "21", type="int")
        if context == "repl":
            self.assertEvaluate("", "21", type="int")
            self.assertEvaluate("", "21", type="int")
        self.assertEvaluate("static_int", "0x0000002a", type="int", is_hex=True)
        self.assertEvaluate("non_static_int", "0x0000002b", type="int", is_hex=True)
        self.assertEvaluate("struct1.foo", "0x0000000f", type="int", is_hex=True)
        self.assertEvaluate("struct2->foo", "0x00000010", type="int", is_hex=True)
        self.assertEvaluate("static_int", "42", type="int")
        self.assertEvaluate("non_static_int", "43", type="int")
        self.assertEvaluate("struct1.foo", "15", type="int")
        self.assertEvaluate("struct2->foo", "16", type="int")

        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "struct1",
                r"\(my_struct\) (struct1|\$\d+) = \(foo = 15\)",
                type="my_struct",
                has_var_ref=True,
            )
            self.assertEvaluate(
                "struct2",
                r"\(my_struct \*\) (struct2|\$\d+) = 0x.*",
                type="my_struct *",
                has_var_ref=True,
            )
            self.assertEvaluate(
                "struct3",
                r"\(my_struct \*\) (struct3|\$\d+) = nullptr",
                type="my_struct *",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "struct1", "(foo = 15)", type="my_struct", has_var_ref=True
            )
            self.assertEvaluate(
                "struct2", r"0x.*", type="my_struct *", has_var_ref=True
            )
            self.assertEvaluate(
                "struct3", "nullptr", type="my_struct *", has_var_ref=True
            )
        else:
            self.assertEvaluate(
                "struct1",
                (re.escape("{foo:15}") if enableAutoVariableSummaries else "my_struct"),
                has_var_ref=True,
            )
            self.assertEvaluate(
                "struct2",
                "0x.* {foo:16}" if enableAutoVariableSummaries else "0x.*",
                has_var_ref=True,
                type="my_struct *",
            )
            self.assertEvaluate(
                "struct3", "0x.*0", has_var_ref=True, type="my_struct *"
            )

        if context == "repl" or context is None:
            # In repl or unknown context expressions may be interpreted as lldb
            # commands since no variables have the same name as the command.
            self.assertEvaluate("list", r".*", has_mem_ref=False)
            # Changing the frame index should not make a difference.
            self.assertEvaluate(
                "version", r".*lldb.+", has_mem_ref=False, frame_index=1
            )
        else:
            self.assertEvaluateFailure("list")  # local variable of a_function

        self.assertEvaluateFailure("my_struct")  # type name
        self.assertEvaluateFailure("int")  # type name
        self.assertEvaluateFailure("foo")  # member of my_struct

        if self.isExpressionParsedExpected():
            self.assertEvaluate(
                "a_function",
                "0x.*a.out`a_function.*",
                type="int (*)(int)",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.assertEvaluate("a_function(1)", "1", has_mem_ref=False, type="int")
            self.assertEvaluate("var2 + struct1.foo", "36", has_mem_ref=False)
            self.assertEvaluate(
                "foo_func",
                "0x.*a.out`foo_func.*",
                type="int (*)()",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.assertEvaluate("foo_var", "44")
        else:
            self.assertEvaluateFailure("a_function")
            self.assertEvaluateFailure("a_function(1)")
            self.assertEvaluateFailure("var2 + struct1.foo")
            self.assertEvaluateFailure("foo_func")
            self.assertEvaluateFailure("(float) var2")
            self.assertEvaluate("foo_var", "44")

        # Expressions at breakpoint 2, which is an anonymous block.
        self._session.continue_to_breakpoint(bp2)
        self.assertEvaluate("var1", "20")
        self.assertEvaluate("var2", "2")  # different variable with the same name
        self.assertEvaluate("static_int", "42")
        # different variable with the same name
        self.assertEvaluate("non_static_int", "10")
        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "struct1",
                r"\(my_struct\) (struct1|\$\d+) = \(foo = 15\)",
                type="my_struct",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "struct1", "(foo = 15)", type="my_struct", has_var_ref=True
            )
        else:
            self.assertEvaluate(
                "struct1",
                (re.escape("{foo:15}") if enableAutoVariableSummaries else "my_struct"),
                type="my_struct",
                has_var_ref=True,
            )
        self.assertEvaluate("struct1.foo", "15")
        self.assertEvaluate("struct2->foo", "16")

        if self.isExpressionParsedExpected():
            self.assertEvaluate(
                "a_function",
                "0x.*a.out`a_function.*",
                type="int (*)(int)",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.assertEvaluate("a_function(1)", "1", has_mem_ref=False)
            self.assertEvaluate("var2 + struct1.foo", "17", has_mem_ref=False)
            self.assertEvaluate(
                "foo_func", "0x.*a.out`foo_func.*", has_var_ref=True, has_mem_ref=False
            )
            self.assertEvaluate("foo_var", "44")
        else:
            self.assertEvaluateFailure("a_function")
            self.assertEvaluateFailure("a_function(1)")
            self.assertEvaluateFailure("var2 + struct1.foo")
            self.assertEvaluateFailure("foo_func")
            self.assertEvaluate("foo_var", "44")

        # Expressions at breakpoint 3, which is inside a_function.
        self._session.continue_to_breakpoint(bp3)
        self.assertEvaluate("list", "42")
        self.assertEvaluate("static_int", "42")
        self.assertEvaluate("non_static_int", "43")
        # variable from a different frame
        self.assertEvaluate("var1", "20", frame_index=1)

        if self.isExpressionParsedExpected():
            # access global variable without a frame
            # Run in variable mode to avoid interpreting it as a command.
            self._session.evaluate("`lldb-dap repl-mode variable", context="repl")
            self.assertEvaluate("static_int", "42", frame_index=None, has_mem_ref=None)
            self._session.evaluate("`lldb-dap repl-mode auto", context="repl")

        self.assertEvaluateFailure("var1")
        self.assertEvaluateFailure("var2")
        self.assertEvaluateFailure("struct1")
        self.assertEvaluateFailure("struct1.foo")
        self.assertEvaluateFailure("struct2->foo")
        self.assertEvaluateFailure("var2 + struct1.foo")

        if self.isExpressionParsedExpected():
            self.assertEvaluate(
                "a_function",
                "0x.*a.out`a_function.*",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.assertEvaluate("a_function(1)", "1", has_mem_ref=False)
            self.assertEvaluate("list + 1", "43", has_mem_ref=False)
            self.assertEvaluate(
                "foo_func", "0x.*a.out`foo_func.*", has_var_ref=True, has_mem_ref=False
            )
            self.assertEvaluate("foo_var", "44")
        else:
            self.assertEvaluateFailure("a_function")
            self.assertEvaluateFailure("a_function(1)")
            self.assertEvaluateFailure("list + 1")
            self.assertEvaluateFailure("foo_func")
            self.assertEvaluate("foo_var", "44")

        # Now check that values are updated after stepping.
        self._session.continue_to_breakpoint(bp4)
        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "my_vec",
                r"\(std::vector<int>\) \$\d+ = size=2 {\n  \[0\] = 1\n  \[1\] = 2\n}",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "my_vec", r"size=2 {\n  \[0\] = 1\n  \[1\] = 2\n}", has_var_ref=True
            )
        else:
            self.assertEvaluate("my_vec", "size=2", has_var_ref=True)
        self._session.continue_to_breakpoint(bp5)
        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "my_vec",
                r"\(std::vector<int>\) \$\d+ = size=3 {\n  \[0\] = 1\n  \[1\] = 2\n  \[2\] = 3\n}",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "my_vec",
                r"size=3 {\n  \[0\] = 1\n  \[1\] = 2\n  \[2\] = 3\n}",
                has_var_ref=True,
            )
        else:
            self.assertEvaluate("my_vec", "size=3", has_var_ref=True)

        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "my_map",
                r"\(std::map<int, int>\) \$\d+ = size=2 {\n  \[0\] = \(first = 1, second = 2\)\n  \[1\] = \(first = 2, second = 3\)\n}",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "my_map",
                r"size=2 {\n  \[0\] = \(first = 1, second = 2\)\n  \[1\] = \(first = 2, second = 3\)\n}",
                has_var_ref=True,
            )
        else:
            self.assertEvaluate("my_map", "size=2", has_var_ref=True)
        self._session.continue_to_breakpoint(bp6)
        self.assertEvaluate("my_map", "size=3", has_var_ref=True)

        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "my_bool_vec",
                r"\(std::vector<bool>\) \$\d+ = size=1 {\n  \[0\] = true\n}",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "my_bool_vec", r"size=1 {\n  \[0\] = true\n}", has_var_ref=True
            )
        else:
            self.assertEvaluate("my_bool_vec", "size=1", has_var_ref=True)
        self._session.continue_to_breakpoint(bp7)
        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "my_bool_vec",
                r"\(std::vector<bool>\) \$\d+ = size=2 {\n  \[0\] = true\n  \[1\] = false\n}",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "my_bool_vec",
                r"size=2 {\n  \[0\] = true\n  \[1\] = false\n}",
                has_var_ref=True,
            )
        else:
            self.assertEvaluate("my_bool_vec", "size=2", has_var_ref=True)

        self._session.continue_to_breakpoint(bp8)
        # Test memory read, especially with 'empty' repeat commands.
        if context == "repl":
            self.assertEvaluate(
                "memory read -c 1 &my_ints", ".* 05 .*\n", has_mem_ref=False
            )
            self.assertEvaluate("", ".* 0a .*\n", has_mem_ref=False)
            self.assertEvaluate("", ".* 0f .*\n", has_mem_ref=False)
            self.assertEvaluate("", ".* 14 .*\n", has_mem_ref=False)
            self.assertEvaluate("", ".* 19 .*\n", has_mem_ref=False)

        if self.isResultExpandedDescription():
            self.assertEvaluate(
                "my_longs",
                r"\(long\[3\]\) \$\d+ = \(\[0\] = 5, \[1\] = 6, \[2\] = 7\)",
                has_var_ref=True,
            )
        elif self.isResultShortDescription():
            self.assertEvaluate(
                "my_longs",
                r"\(\[0\] = 5, \[1\] = 6, \[2\] = 7\)",
                has_var_ref=True,
            )
        else:
            self.assertEvaluate(
                "my_longs",
                "{5, 6, 7}" if enableAutoVariableSummaries else r"long\[3\]",
                has_var_ref=True,
            )

        self._session.continue_to_exit()

    @skipIfWindows
    def test_generic_evaluate_expressions(self):
        # Tests context-less expression evaluations.
        self.run_test_evaluate_expressions(enableAutoVariableSummaries=False)

    @skipIfWindows
    def test_repl_evaluate_expressions(self):
        # Tests expression evaluations triggered from the Debug Console.
        self.run_test_evaluate_expressions("repl", enableAutoVariableSummaries=False)

    @skipIfWindows
    def test_watch_evaluate_expressions(self):
        # Tests expression evaluations triggered from a watch expression.
        self.run_test_evaluate_expressions("watch", enableAutoVariableSummaries=True)

    @skipIfWindows
    def test_hover_evaluate_expressions(self):
        # Tests expression evaluations triggered when hovering on the editor.
        self.run_test_evaluate_expressions("hover", enableAutoVariableSummaries=False)

    @skipIfWindows
    def test_variable_evaluate_expressions(self):
        # Tests expression evaluations triggered in the variable explorer.
        self.run_test_evaluate_expressions(
            "variables", enableAutoVariableSummaries=True
        )

    @skipIfWindows
    def test_clipboard_evaluate_expressions(self):
        # Tests expression evaluations triggered when value is copied in editor.
        self.run_test_evaluate_expressions(
            "clipboard", enableAutoVariableSummaries=False
        )
