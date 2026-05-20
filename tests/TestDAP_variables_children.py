from lldb_dap.dap_types import LaunchArgs, VariablesArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.decorators import skipif_darwin
from lldbsuite.test.lldbtest import line_number


class TestDAP_variables_children(DAPTestCaseBase):
    TEST_PROGRAM = r"""
struct Indexed {};
struct NotIndexed {};

#define BUFFER_SIZE 16
struct NonPrimitive {
  char buffer[BUFFER_SIZE];
  int x;
  long y;
};

NonPrimitive test_return_variable_with_children() {
  return NonPrimitive{"hello world!", 10, 20};
}

int main() {
  Indexed indexed;
  NotIndexed not_indexed;
  NonPrimitive non_primitive_result = test_return_variable_with_children();
  return 0; // break here
}

"""
    FORMATTER_PY = r"""
import lldb

num_children_calls = []


class TestSyntheticProvider:
    def __init__(self, valobj, dict):
        target = valobj.GetTarget()
        self._type = valobj.GetType()
        data = lldb.SBData.CreateDataFromCString(lldb.eByteOrderLittle, 8, "S")
        name = "child" if "Not" in self._type.GetName() else "[0]"
        self._child = valobj.CreateValueFromData(
            name, data, target.GetBasicType(lldb.eBasicTypeChar)
        )

    def num_children(self):
        num_children_calls.append(self._type.GetName())
        return 1

    def get_child_at_index(self, index):
        if index != 0:
            return None
        return self._child

    def get_child_index(self, name):
        if name == self._child.GetName():
            return 0
        return None


def __lldb_init_module(debugger, dict):
    cat = debugger.CreateCategory("TestCategory")
    cat.AddTypeSynthetic(
        lldb.SBTypeNameSpecifier("Indexed"),
        lldb.SBTypeSynthetic.CreateWithClassName("formatter.TestSyntheticProvider"),
    )
    cat.AddTypeSynthetic(
        lldb.SBTypeNameSpecifier("NotIndexed"),
        lldb.SBTypeSynthetic.CreateWithClassName("formatter.TestSyntheticProvider"),
    )
    cat.SetEnabled(True)
"""

    def test_get_num_children(self):
        """Test that GetNumChildren is not called for formatters not producing indexed children."""
        session = self.build_and_create_session()
        source = self.getBuildArtifact("main.cpp")
        program = self.create_test_program_with_name(source)
        self.create_file(self.FORMATTER_PY, "formatter.py")
        # session.launch_using_config(config)
        # TODO this should work
        breakpoint_line = line_number(source, "// break here")
        with session.configure(
            LaunchArgs(
                program,
                preRunCommands=[
                    "command script import '%s'" % self.getSourcePath("formatter.py")
                ],
            )
        ) as ctx:
            session.resolve_source_breakpoints(source, [breakpoint_line])
        process_event = ctx.process_event()
        stopped_event = session.verify_stopped_on_breakpoint(after=process_event)
        thread = session.get_thread_context(stopped_event.body.threadId)
        local_vars = thread.top_frame().locals.variables()
        indexed_var = next(filter(lambda x: x.name == "indexed", local_vars))
        not_indexed_var = next(filter(lambda x: x.name == "not_indexed", local_vars))

        self.assertIsNotNone(indexed_var.indexedVariables)
        self.assertEqual(indexed_var.indexedVariables, 1)
        self.assertIsNone(not_indexed_var.indexedVariables)

        resp_body = session.evaluate(
            "`script formatter.num_children_calls", context="repl"
        )
        self.assertIn("['Indexed']", resp_body.result)

    # @expectedFailureAll(archs=["arm$", "arm64", "aarch64"]) # TODO
    @skipif_darwin()
    def test_return_variable_with_children(self):
        """
        Test the stepping out of a function with return value show the children correctly
        """
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")

        with session.configure(LaunchArgs(program)) as ctx:
            function_name = "test_return_variable_with_children"
            breakpoint_ids = session.resolve_function_breakpoints([function_name])
            self.assertEqual(len(breakpoint_ids), 1)

        stopped_event = session.wait_until_any_breakpoint_hit(
            breakpoint_ids, after=ctx.process_event()
        )

        thread_id = self.expect_is_not_none(
            stopped_event.body.threadId,
            f"no thread id for stopped event {stopped_event}",
        )
        self.assertEqual(stopped_event.body.reason, "breakpoint")

        thread = session.get_thread_context(thread_id)
        thread.step_out()
        local_variables = thread.top_frame().locals.variables()
        self.assertIsNot(len(local_variables), 0)
        return_variable = local_variables[0]
        self.assertEqual(return_variable.name, "(Return Value)")

        result_var_ref = return_variable.variablesReference
        self.assertIsNot(result_var_ref, None, "There is no result value")

        result_value = session.request_and_respond(VariablesArgs(result_var_ref))
        result_children = result_value.body.variables
        self.assertTrue(result_children, "The result does not have children")

        verify_children = {"buffer": '"hello world!"', "x": "10", "y": "20"}
        for child in result_children:
            verify_value = verify_children.get(child.name)
            self.assertNotEqual(verify_value, None)
            self.assertEqual(
                child.value, verify_value, "Expected child value does not match"
            )
