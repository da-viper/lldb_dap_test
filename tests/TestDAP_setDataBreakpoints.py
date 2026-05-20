"""
Test lldb-dap dataBreakpointInfo and setDataBreakpoints requests
"""

from lldb_dap.dap_types import DataBreakpoint, LaunchArgs
from lldb_dap.lldb_dap_testcase import DAPTestCaseBase
from lldbsuite.test.decorators import skipIfWindows
from lldbsuite.test.lldbtest import line_number


class TestDAP_setDataBreakpoints(DAPTestCaseBase):
    ACCESS_TYPES = ["read", "write", "readWrite"]

    @skipIfWindows
    def test_duplicate_start_addresses(self):
        """Test setDataBreakpoints with multiple watchpoints starting at the same addresses."""
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        source = self.getSourcePath("main.cpp")
        first_loop_break_line = line_number(source, "// first loop breakpoint")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [first_loop_break_line])
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        # Test setting write watchpoint using expressions: &x, arr+2
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_id = thread_ctx.top_frame().frame.id
        response_x = session.data_breakpoint_info("&x", 0, top_frame_id)
        response_arr_2 = session.data_breakpoint_info("arr+2", 0, top_frame_id)

        # Test response from dataBreakpointInfo request.
        x_data_id = self.expect_is_not_none(response_x.body.dataId)
        arr_2_data_id = self.expect_is_not_none(response_arr_2.body.dataId)
        self.assertEqual(x_data_id.split("/")[1], "4")
        self.assertEqual(response_x.body.accessTypes, self.ACCESS_TYPES)
        self.assertEqual(arr_2_data_id.split("/")[1], "4")
        self.assertEqual(response_arr_2.body.accessTypes, self.ACCESS_TYPES)
        # The first one should be overwritten by the third one as they start at
        # the same address. This is indicated by returning {verified: False} for
        # the first one.
        dataBreakpoints = [
            DataBreakpoint(dataId=x_data_id, accessType="read"),
            DataBreakpoint(dataId=arr_2_data_id, accessType="write"),
            DataBreakpoint(dataId=x_data_id, accessType="write"),
        ]
        set_response = session.set_data_breakpoints(dataBreakpoints)
        breakpoints = set_response.body.breakpoints
        self.assertEqual(len(breakpoints), 3)
        self.assertFalse(breakpoints[0].verified)
        self.assertTrue(breakpoints[1].verified)
        self.assertTrue(breakpoints[2].verified)

        breakpoint2_id = self.expect_is_not_none(breakpoints[2].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint2_id])
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()

        x_val = top_frame_ctx.locals["x"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(x_val.value, "2")
        self.assertEqual(i_val.value, "1")

        breakpoint1_id = self.expect_is_not_none(breakpoints[1].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint1_id])

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        # TODO: simplify this to (get_local_variable("arr").get_child("[2]"))
        arr = top_frame_ctx.locals["arr"]
        arr_2 = arr["[2]"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(arr_2.value, "42")
        self.assertEqual(i_val.value, "2")

        session.set_data_breakpoints([])
        session.continue_to_exit()

    @skipIfWindows
    def test_expression(self):
        """Tests setting data breakpoints on expression."""
        source = self.getSourcePath("main.cpp")
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        first_loop_break_line = line_number(source, "// first loop breakpoint")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [first_loop_break_line])
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        # Test setting write watchpoint using expressions: &x, arr+2
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_id = thread_ctx.top_frame().frame.id
        response_x = session.data_breakpoint_info("&x", 0, top_frame_id)
        response_arr_2 = session.data_breakpoint_info("arr+2", 0, top_frame_id)

        # Test response from dataBreakpointInfo request.
        response_x_data_id = self.expect_is_not_none(response_x.body.dataId)
        response_arr_2_data_id = self.expect_is_not_none(response_arr_2.body.dataId)
        self.assertEqual(response_x_data_id.split("/")[1], "4")
        self.assertEqual(response_x.body.accessTypes, self.ACCESS_TYPES)
        self.assertEqual(response_arr_2_data_id.split("/")[1], "4")
        self.assertEqual(response_arr_2.body.accessTypes, self.ACCESS_TYPES)

        data_breakpoints = [
            DataBreakpoint(dataId=response_x_data_id, accessType="write"),
            DataBreakpoint(dataId=response_arr_2_data_id, accessType="write"),
        ]
        set_response = session.set_data_breakpoints(data_breakpoints)
        breakpoints = set_response.body.breakpoints
        self.assertEqual(len(breakpoints), len(data_breakpoints))
        self.assertTrue(breakpoints[0].verified)
        self.assertTrue(breakpoints[1].verified)

        breakpoint0_id = self.expect_is_not_none(breakpoints[0].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint0_id])
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()

        x_val = top_frame_ctx.locals["x"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(x_val.value, "2")
        self.assertEqual(i_val.value, "1")

        breakpoint1_id = self.expect_is_not_none(breakpoints[1].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint1_id])

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        # TODO: simplify this to (get_local_variable("arr").get_child("[2]"))
        arr = top_frame_ctx.locals["arr"]
        arr_2 = arr["[2]"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(arr_2.value, "42")
        self.assertEqual(i_val.value, "2")
        session.set_data_breakpoints([])
        session.continue_to_exit()

    # TODO: renable windows
    @skipIfWindows
    def test_functionality(self):
        """Tests setting data breakpoints on variable."""
        source = self.getSourcePath("main.cpp")
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        first_loop_break_line = line_number(source, "// first loop breakpoint")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [first_loop_break_line])
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        locals_ref = top_frame_ctx.locals.variablesReference
        # Test write watchpoints on x, arr[2]
        frame_id = top_frame_ctx.frame.id
        response_x = session.data_breakpoint_info("x", locals_ref, frame_id)
        arr = top_frame_ctx.locals["arr"]
        arr_var_ref = self.expect_is_not_none(arr.variablesReference)
        response_arr_2 = session.data_breakpoint_info("[2]", arr_var_ref, frame_id)

        # Test response from dataBreakpointInfo request.
        x_data_id = self.expect_is_not_none(response_x.body.dataId)
        response_arr_2_data_id = self.expect_is_not_none(response_arr_2.body.dataId)
        self.assertEqual(x_data_id.split("/")[1], "4")
        self.assertEqual(response_x.body.accessTypes, self.ACCESS_TYPES)
        self.assertEqual(response_arr_2_data_id.split("/")[1], "4")
        self.assertEqual(response_arr_2.body.accessTypes, self.ACCESS_TYPES)

        data_breakpoints = [
            DataBreakpoint(dataId=x_data_id, accessType="write"),
            DataBreakpoint(dataId=response_arr_2_data_id, accessType="write"),
        ]
        set_response = session.set_data_breakpoints(data_breakpoints)
        breakpoints = set_response.body.breakpoints
        self.assertEqual(len(breakpoints), len(data_breakpoints))
        self.assertTrue(breakpoints[0].verified)
        self.assertTrue(breakpoints[1].verified)

        breakpoint0_id = self.expect_is_not_none(breakpoints[0].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint0_id])
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()

        x_var = top_frame_ctx.locals["x"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(x_var.value, "2")
        self.assertEqual(i_val.value, "1")

        breakpoint1_id = self.expect_is_not_none(breakpoints[1].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint1_id])

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        # TODO: simplify this to (get_local_variable("arr").get_child("[2]"))
        arr_2 = top_frame_ctx.locals["arr"]["[2]"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(arr_2.value, "42")
        self.assertEqual(i_val.value, "2")

        session.set_data_breakpoints([])

        # Test hit condition
        second_loop_break_line = line_number(source, "// second loop breakpoint")
        breakpoint_ids = session.resolve_source_breakpoints(
            source, [second_loop_break_line]
        )
        stop_event = session.continue_to_any_breakpoint(breakpoint_ids)
        data_breakpoints = [
            DataBreakpoint(dataId=x_data_id, accessType="write", hitCondition="2")
        ]
        set_response = session.set_data_breakpoints(data_breakpoints)
        breakpoints = set_response.body.breakpoints
        self.assertEqual(len(breakpoints), len(data_breakpoints))
        self.assertTrue(breakpoints[0].verified)
        breakpoint0_id = self.expect_is_not_none(breakpoints[0].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint0_id])

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        x_var = top_frame_ctx.locals["x"]
        self.assertEqual(x_var.value, "3")

        # Test condition
        data_breakpoints = [
            DataBreakpoint(dataId=x_data_id, accessType="write", condition="x==10")
        ]
        set_response = session.set_data_breakpoints(data_breakpoints)
        breakpoints = set_response.body.breakpoints
        self.assertEqual(len(breakpoints), len(data_breakpoints))
        self.assertTrue(breakpoints[0].verified)
        breakpoint0_id = self.expect_is_not_none(breakpoints[0].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint0_id])

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        x_var = top_frame_ctx.locals["x"]
        self.assertEqual(x_var.value, "10")

    @skipIfWindows
    def test_bytes(self):
        """Tests setting data breakpoints on memory range."""
        source = self.getSourcePath("main.cpp")
        program = self.getBuildArtifact("a.out")
        session = self.build_and_create_session()
        first_loop_break_line = line_number(source, "// first loop breakpoint")
        with session.configure(LaunchArgs(program)) as ctx:
            session.resolve_source_breakpoints(source, [first_loop_break_line])
        process_event = ctx.process_event()
        stop_event = session.verify_stopped_on_breakpoint(after=process_event)

        # Test write watchpoints on x, arr[2]
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        x = top_frame_ctx.locals["x"]
        x_memory_reference = self.expect_is_not_none(x.memoryReference)
        response_x = session.data_breakpoint_info_as_address(x_memory_reference, 4)
        arr = top_frame_ctx.locals["arr"]
        arr_2 = arr["[2]"]
        arr_2_mem_ref = self.expect_is_not_none(arr_2.memoryReference)
        response_arr_2 = session.data_breakpoint_info_as_address(arr_2_mem_ref, 4)

        # Test response from dataBreakpointInfo request.
        x_data_id = self.expect_is_not_none(response_x.body.dataId)
        self.assertEqual(x_data_id.split("/"), [x_memory_reference[2:], "4"])
        self.assertEqual(response_x.body.accessTypes, self.ACCESS_TYPES)
        arr_2_data_id = self.expect_is_not_none(response_arr_2.body.dataId)
        arr_2_mem_ref = self.expect_is_not_none(arr_2.memoryReference)
        self.assertEqual(arr_2_data_id.split("/"), [arr_2_mem_ref[2:], "4"])
        self.assertEqual(response_arr_2.body.accessTypes, self.ACCESS_TYPES)

        data_breakpoints = [
            DataBreakpoint(dataId=x_data_id, accessType="write"),
            DataBreakpoint(dataId=arr_2_data_id, accessType="write"),
        ]
        set_response = session.set_data_breakpoints(data_breakpoints)
        breakpoints = set_response.body.breakpoints
        self.assertEqual(len(breakpoints), len(data_breakpoints))
        self.assertTrue(breakpoints[0].verified)
        self.assertTrue(breakpoints[1].verified)

        breakpoint0_id = self.expect_is_not_none(breakpoints[0].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint0_id])
        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()

        x_val = top_frame_ctx.locals["x"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(x_val.value, "2")
        self.assertEqual(i_val.value, "1")

        breakpoint1_id = self.expect_is_not_none(breakpoints[1].id)
        stop_event = session.continue_to_any_breakpoint([breakpoint1_id])

        thread_ctx = session.get_thread_context(stop_event.body.threadId)
        top_frame_ctx = thread_ctx.top_frame()
        # TODO: simplify this to (get_local_variable("arr").get_child("[2]"))
        arr = top_frame_ctx.locals["arr"]
        arr_2 = arr["[2]"]
        i_val = top_frame_ctx.locals["i"]
        self.assertEqual(arr_2.value, "42")
        self.assertEqual(i_val.value, "2")

        session.set_data_breakpoints([])
        session.continue_to_exit()


    TEST_PROGRAM = r"""
int main(int argc, char const *argv[]) {
  // Test for data breakpoint
  int x = 0;
  int arr[4] = {1, 2, 3, 4};
  for (int i = 0; i < 5; ++i) { // first loop breakpoint
    if (i == 1) {
      x = i + 1;
    } else if (i == 2) {
      arr[i] = 42;
    }
  }

  x = 1;
  for (int i = 0; i < 10; ++i) { // second loop breakpoint
    ++x;
  }
}

"""
