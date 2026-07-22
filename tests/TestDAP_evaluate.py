"""Test lldb-dap evaluate request."""

import re
from typing import Optional

from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import (
    ErrorResponse,
    EvaluateContext,
    LaunchArgs,
    ValueFormat,
)
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


def expects_expanded_description(context: Optional[EvaluateContext]) -> bool:
    """Result has a fully-expanded description (with type prefix, etc.)."""
    return context == "repl"


def expects_short_description(context: Optional[EvaluateContext]) -> bool:
    """Result has a short description (summary only, no type prefix)."""
    return context == "clipboard"


def expects_parsed_expression(context: Optional[EvaluateContext]) -> bool:
    """Expression is parsed as C/C++ (function calls, arithmetic, ...)."""
    return context != "hover"


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

    def expect_eval(
        self,
        expression: str,
        *,
        as_hex: bool = False,
        **expected_kwargs,
    ):
        """Evaluate `expression` in the eval_frame and verify its response."""
        expected_kwargs.setdefault("has_mem_ref", True)

        eval_body = self._session.evaluate(
            expression,
            frameId=self._eval_frame.id,
            context=self._context,
            format=ValueFormat(hex=True) if as_hex else None,
        )
        self._session.verify_evaluate(eval_body, **expected_kwargs)

    def expect_eval_failure(self, expression: str):
        """Evaluate `expression` in the eval_frame and assert that it fails."""
        resp_pending = self._session.do_evaluate(
            expression, frameId=self._eval_frame.id, context=self._context
        )
        response = resp_pending.result_or_error()
        if isinstance(response, ErrorResponse):
            return
        if response.body.result.startswith("error:"):
            return

        self.fail(
            f"{expression=!r} should fail in {self._context!r} context, got {response!r}"
        )

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

    def run_test_evaluate_expressions(
        self,
        context: Optional[EvaluateContext] = None,
        enableAutoVariableSummaries: bool = False,
    ):
        """Tests the evaluate expression request at different breakpoints."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = "main.cpp"

        # Bindings read by `expect_evaluate` / `expect_evaluate_failure`.
        self._session = session
        self._context: Optional[EvaluateContext] = context

        launch_args = LaunchArgs(
            program=program, enableAutoVariableSummaries=enableAutoVariableSummaries
        )
        with session.configure(launch_args) as ctx:
            breakpoint_lines = [
                line_number(source, "// breakpoint 1"),
                line_number(source, "// breakpoint 2"),
                line_number(source, "// breakpoint 3"),
                line_number(source, "// breakpoint 4"),
                line_number(source, "// breakpoint 5"),
                line_number(source, "// breakpoint 6"),
                line_number(source, "// breakpoint 7"),
                line_number(source, "// breakpoint 8"),
            ]
            breakpoint_ids = session.resolve_source_breakpoints(
                source, breakpoint_lines
            )

        bp1, bp2, bp3, bp4, bp5, bp6, bp7, bp8 = breakpoint_ids

        # Breakpoint 1.
        stop = session.verify_stopped_on_breakpoint(bp1, after=ctx.process_event)
        thread_ctx = session.thread_context_from(stop)
        self._eval_frame = thread_ctx.top_frame()

        self.expect_eval("var1", matches="20", type="int")
        # Empty expression should equate to the previous expression in repl.
        if context == "repl":
            self.expect_eval("", matches="20")
        else:
            self.expect_eval_failure("")
        self.expect_eval("var2", matches="21", type="int")
        if context == "repl":
            self.expect_eval("", matches="21", type="int")
            self.expect_eval("", matches="21", type="int")
        self.expect_eval("static_int", as_hex=True, matches="0x0000002a", type="int")
        self.expect_eval(
            "non_static_int", as_hex=True, matches="0x0000002b", type="int"
        )
        self.expect_eval("struct1.foo", as_hex=True, matches="0x0000000f", type="int")
        self.expect_eval("struct2->foo", as_hex=True, matches="0x00000010", type="int")
        self.expect_eval("static_int", matches="42", type="int")
        self.expect_eval("non_static_int", matches="43", type="int")
        self.expect_eval("struct1.foo", matches="15", type="int")
        self.expect_eval("struct2->foo", matches="16", type="int")

        if expects_expanded_description(context):
            self.expect_eval(
                "struct1",
                matches=r"\(my_struct\) (struct1|\$\d+) = \(foo = 15\)",
                type="my_struct",
                has_var_ref=True,
            )
            self.expect_eval(
                "struct2",
                matches=r"\(my_struct \*\) (struct2|\$\d+) = 0x.*",
                type="my_struct *",
                has_var_ref=True,
            )
            self.expect_eval(
                "struct3",
                matches=r"\(my_struct \*\) (struct3|\$\d+) = nullptr",
                type="my_struct *",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "struct1",
                matches="(foo = 15)",
                type="my_struct",
                has_var_ref=True,
            )
            self.expect_eval(
                "struct2",
                matches=r"0x.*",
                type="my_struct *",
                has_var_ref=True,
            )
            self.expect_eval(
                "struct3",
                matches="nullptr",
                type="my_struct *",
                has_var_ref=True,
            )
        else:
            self.expect_eval(
                "struct1",
                matches=(
                    re.escape("{foo:15}")
                    if enableAutoVariableSummaries
                    else "my_struct"
                ),
                has_var_ref=True,
            )
            self.expect_eval(
                "struct2",
                matches=("0x.* {foo:16}" if enableAutoVariableSummaries else "0x.*"),
                type="my_struct *",
                has_var_ref=True,
            )
            self.expect_eval(
                "struct3", matches="0x.*0", type="my_struct *", has_var_ref=True
            )

        if context == "repl" or context is None:
            # In repl or unknown context expressions may be interpreted as lldb
            # commands since no variables have the same name as the command.
            self.expect_eval("list", matches=r".*", has_mem_ref=False)
            # Changing the frame index should not make a difference.
            thread_ctx = session.thread_context_from(stop)
            [_, frame_2] = thread_ctx.frames(levels=2)
            body = session.evaluate("version", frameId=frame_2.id, context=context)
            session.verify_evaluate(body, matches=r".*lldb.+", has_mem_ref=False)
        else:
            self.expect_eval_failure("list")  # local variable of a_function

        self.expect_eval_failure("my_struct")  # type name
        self.expect_eval_failure("int")  # type name
        self.expect_eval_failure("foo")  # member of my_struct

        if expects_parsed_expression(context):
            self.expect_eval(
                "a_function",
                matches="0x.*a.out`a_function.*",
                type="int (*)(int)",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.expect_eval(
                "a_function(1)", matches="1", type="int", has_mem_ref=False
            )
            self.expect_eval("var2 + struct1.foo", matches="36", has_mem_ref=False)
            self.expect_eval(
                "foo_func",
                matches="0x.*a.out`foo_func.*",
                type="int (*)()",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.expect_eval("foo_var", matches="44")
        else:
            self.expect_eval_failure("a_function")
            self.expect_eval_failure("a_function(1)")
            self.expect_eval_failure("var2 + struct1.foo")
            self.expect_eval_failure("foo_func")
            self.expect_eval_failure("(float) var2")
            self.expect_eval("foo_var", matches="44")

        # Breakpoint 2: In an anonymous block.
        session.continue_to_breakpoint(bp2)
        self._eval_frame = thread_ctx.top_frame()

        self.expect_eval("var1", matches="20")
        self.expect_eval("var2", matches="2")  # Shadowed var2.
        self.expect_eval("static_int", matches="42")
        self.expect_eval("non_static_int", matches="10")  # Shadowed non_static_int.

        if expects_expanded_description(context):
            self.expect_eval(
                "struct1",
                matches=r"\(my_struct\) (struct1|\$\d+) = \(foo = 15\)",
                type="my_struct",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "struct1",
                matches="(foo = 15)",
                type="my_struct",
                has_var_ref=True,
            )
        else:
            self.expect_eval(
                "struct1",
                matches=(
                    re.escape("{foo:15}")
                    if enableAutoVariableSummaries
                    else "my_struct"
                ),
                type="my_struct",
                has_var_ref=True,
            )
        self.expect_eval("struct1.foo", matches="15")
        self.expect_eval("struct2->foo", matches="16")

        if expects_parsed_expression(context):
            self.expect_eval(
                "a_function",
                matches="0x.*a.out`a_function.*",
                type="int (*)(int)",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.expect_eval("a_function(1)", matches="1", has_mem_ref=False)
            self.expect_eval("var2 + struct1.foo", matches="17", has_mem_ref=False)
            self.expect_eval(
                "foo_func",
                matches="0x.*a.out`foo_func.*",
                has_var_ref=True,
                has_mem_ref=False,
            )
            self.expect_eval("foo_var", matches="44")
        else:
            self.expect_eval_failure("a_function")
            self.expect_eval_failure("a_function(1)")
            self.expect_eval_failure("var2 + struct1.foo")
            self.expect_eval_failure("foo_func")
            self.expect_eval("foo_var", matches="44")

        # Breakpoint 3: Inside 'a_function'.
        session.continue_to_breakpoint(bp3)
        self._eval_frame = thread_ctx.top_frame()
        parent_frame = thread_ctx.frames(levels=2)[1]

        self.expect_eval("list", matches="42")
        self.expect_eval("static_int", matches="42")
        self.expect_eval("non_static_int", matches="43")
        # Variable from a different frame.
        body = session.evaluate("var1", frameId=parent_frame.id, context=context)
        session.verify_evaluate(body, matches="20")

        if expects_parsed_expression(context):
            # Access a global variable without a frame.
            # Run in variable mode to avoid interpreting it as a command.
            session.evaluate("`lldb-dap repl-mode variable", context="repl")
            body = session.evaluate("static_int", frameId=None, context=context)
            session.verify_evaluate(body, matches="42")
            session.evaluate("`lldb-dap repl-mode auto", context="repl")

        self.expect_eval_failure("var1")
        self.expect_eval_failure("var2")
        self.expect_eval_failure("struct1")
        self.expect_eval_failure("struct1.foo")
        self.expect_eval_failure("struct2->foo")
        self.expect_eval_failure("var2 + struct1.foo")

        if expects_parsed_expression(context):
            self.expect_eval(
                "a_function",
                matches="0x.*a.out`a_function.*",
                has_var_ref=True,
                has_mem_ref=False,
                has_loc_ref=True,
            )
            self.expect_eval("a_function(1)", matches="1", has_mem_ref=False)
            self.expect_eval("list + 1", matches="43", has_mem_ref=False)
            self.expect_eval(
                "foo_func",
                matches="0x.*a.out`foo_func.*",
                has_var_ref=True,
                has_mem_ref=False,
            )
            self.expect_eval("foo_var", matches="44")
        else:
            self.expect_eval_failure("a_function")
            self.expect_eval_failure("a_function(1)")
            self.expect_eval_failure("list + 1")
            self.expect_eval_failure("foo_func")
            self.expect_eval("foo_var", matches="44")

        # Breakpoint 4: After two push_backs to my_vec.
        session.continue_to_breakpoint(bp4)
        self._eval_frame = thread_ctx.top_frame()

        if expects_expanded_description(context):
            self.expect_eval(
                "my_vec",
                matches=r"\(std::vector<int>\) \$\d+ = size=2 {\n  \[0\] = 1\n  \[1\] = 2\n}",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "my_vec",
                matches=r"size=2 {\n  \[0\] = 1\n  \[1\] = 2\n}",
                has_var_ref=True,
            )
        else:
            self.expect_eval("my_vec", matches="size=2", has_var_ref=True)

        # Breakpoint 5: after 3rd push into my_vec, and 2 map inserts.
        session.continue_to_breakpoint(bp5)
        self._eval_frame = thread_ctx.top_frame()

        if expects_expanded_description(context):
            self.expect_eval(
                "my_vec",
                matches=r"\(std::vector<int>\) \$\d+ = size=3 {\n  \[0\] = 1\n  \[1\] = 2\n  \[2\] = 3\n}",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "my_vec",
                matches=r"size=3 {\n  \[0\] = 1\n  \[1\] = 2\n  \[2\] = 3\n}",
                has_var_ref=True,
            )
        else:
            self.expect_eval("my_vec", matches="size=3", has_var_ref=True)

        if expects_expanded_description(context):
            self.expect_eval(
                "my_map",
                matches=r"\(std::map<int, int>\) \$\d+ = size=2 {\n  \[0\] = \(first = 1, second = 2\)\n  \[1\] = \(first = 2, second = 3\)\n}",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "my_map",
                matches=r"size=2 {\n  \[0\] = \(first = 1, second = 2\)\n  \[1\] = \(first = 2, second = 3\)\n}",
                has_var_ref=True,
            )
        else:
            self.expect_eval("my_map", matches="size=2", has_var_ref=True)

        # Breakpoint 6: 3rd map insert, first push into my_bool_vec.
        session.continue_to_breakpoint(bp6)
        self._eval_frame = thread_ctx.top_frame()

        self.expect_eval("my_map", matches="size=3", has_var_ref=True)

        if expects_expanded_description(context):
            self.expect_eval(
                "my_bool_vec",
                matches=r"\(std::vector<bool>\) \$\d+ = size=1 {\n  \[0\] = true\n}",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "my_bool_vec",
                matches=r"size=1 {\n  \[0\] = true\n}",
                has_var_ref=True,
            )
        else:
            self.expect_eval("my_bool_vec", matches="size=1", has_var_ref=True)

        # Breakpoint 7: After 2nd push into my_bool_vec.
        session.continue_to_breakpoint(bp7)
        self._eval_frame = thread_ctx.top_frame()

        if expects_expanded_description(context):
            self.expect_eval(
                "my_bool_vec",
                matches=r"\(std::vector<bool>\) \$\d+ = size=2 {\n  \[0\] = true\n  \[1\] = false\n}",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "my_bool_vec",
                matches=r"size=2 {\n  \[0\] = true\n  \[1\] = false\n}",
                has_var_ref=True,
            )
        else:
            self.expect_eval("my_bool_vec", matches="size=2", has_var_ref=True)

        # Breakpoint 8: Before return.
        session.continue_to_breakpoint(bp8)
        self._eval_frame = thread_ctx.top_frame()

        # Test memory read, especially with 'empty' repeat commands.
        if context == "repl":
            self.expect_eval(
                "memory read -c 1 &my_ints", matches=".* 05 .*\n", has_mem_ref=False
            )
            self.expect_eval("", matches=".* 0a .*\n", has_mem_ref=False)
            self.expect_eval("", matches=".* 0f .*\n", has_mem_ref=False)
            self.expect_eval("", matches=".* 14 .*\n", has_mem_ref=False)
            self.expect_eval("", matches=".* 19 .*\n", has_mem_ref=False)

        if expects_expanded_description(context):
            self.expect_eval(
                "my_longs",
                matches=r"\(long\[3\]\) \$\d+ = \(\[0\] = 5, \[1\] = 6, \[2\] = 7\)",
                has_var_ref=True,
            )
        elif expects_short_description(context):
            self.expect_eval(
                "my_longs",
                matches=r"\(\[0\] = 5, \[1\] = 6, \[2\] = 7\)",
                has_var_ref=True,
            )
        else:
            self.expect_eval(
                "my_longs",
                matches=("{5, 6, 7}" if enableAutoVariableSummaries else r"long\[3\]"),
                has_var_ref=True,
            )

        session.continue_to_exit()
