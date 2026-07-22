from lldbsuite.test.decorators import expectedFailureAll, skipIfDarwin
from lldbsuite.test.lldbtest import line_number
from lldbsuite.test.tools.lldb_dap.types import LaunchArgs
from lldbsuite.test.tools.lldb_dap import DAPTestCaseBase


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

    def build(self, filename=None):
        super().build()
        self.create_file(self.FORMATTER_PY, "formatter.py")

    def test_get_num_children(self):
        """Test that GetNumChildren is not called for formatters not producing indexed children."""
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")

        launch_args = LaunchArgs(
            program,
            preRunCommands=[
                f"command script import '{self.getSourcePath('formatter.py')}'"
            ],
        )
        with session.configure(launch_args) as ctx:
            source = self.getSourcePath("main.cpp")
            breakpoint_line = line_number(source, "// break here")
            session.resolve_source_breakpoints(source, [breakpoint_line])

        stopped_event = session.verify_stopped_on_breakpoint(after=ctx.process_event)
        thread = session.thread_context_from(stopped_event)
        local_vars = thread.top_frame().locals.variables()
        indexed_var = next(x for x in local_vars if x.name == "indexed")
        not_indexed_var = next(x for x in local_vars if x.name == "not_indexed")

        self.assertIsNotNone(indexed_var.indexedVariables)
        self.assertEqual(indexed_var.indexedVariables, 1)
        self.assertIsNone(not_indexed_var.indexedVariables)

        resp_body = session.evaluate(
            "`script formatter.num_children_calls", context="repl"
        )
        self.assertIn("['Indexed']", resp_body.result)

    @expectedFailureAll(archs=["arm$", "arm64", "aarch64"])
    @skipIfDarwin
    def test_return_variable_with_children(self):
        """
        Test the stepping out of a function with return value show the children correctly
        """
        session = self.build_and_create_session()
        program = self.getBuildArtifact("a.out")

        with session.configure(LaunchArgs(program)) as ctx:
            function_name = "test_return_variable_with_children"
            [func_bp_id] = session.resolve_function_breakpoints([function_name])

        stopped_event = session.verify_stopped_on_breakpoint(
            func_bp_id, after=ctx.process_event
        )

        thread_ctx = session.thread_context_from(stopped_event)
        thread_ctx.step_out()

        local_variables = thread_ctx.top_frame().locals.variables()
        self.assertIsNot(len(local_variables), 0)
        return_variable = local_variables[0].variable
        self.assertEqual(return_variable.name, "(Return Value)")

        result_var_ref = return_variable.variablesReference
        self.assertIsNot(result_var_ref, None, "There is no result value")

        result_children = session.get_variables(result_var_ref)
        verify_children = {"buffer": '"hello world!"', "x": "10", "y": "20"}
        for child in result_children:
            verify_value = verify_children.get(child.name)
            self.assertNotEqual(verify_value, None)
            self.assertEqual(
                child.value, verify_value, "Expected child value does not match"
            )
