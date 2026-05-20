import json
import threading
import time
import unittest
from typing import List, Optional

from lldb_dap.dap_types import DAPError, MessageType, RawMessage, Request
from lldb_dap.utils import DAPConnection, MessageHandler, Transport


class FakeTransport:
    """In-memory transport for testing DAPConnection without real I/O."""

    def __init__(self):
        self._cond = threading.Condition()
        self._send_buf = bytearray()
        self._recv_buf = bytearray()
        self._alive = True
        self._error: Optional[Exception] = None

    def write(self, data: bytes) -> None:
        with self._cond:
            self._send_buf += data

    def read(self, n: int) -> bytes:
        with self._cond:
            while not self._recv_buf and self._alive and self._error is None:
                self._cond.wait(timeout=0.05)
            if self._error is not None:
                raise self._error
            if not self._recv_buf:
                return b""
            chunk = bytes(self._recv_buf[:n])
            del self._recv_buf[:n]
            return chunk

    def close(self) -> None:
        with self._cond:
            self._alive = False
            self._cond.notify_all()

    @property
    def is_alive(self) -> bool:
        return self._alive

    def inject(self, data: bytes) -> None:
        """Inject bytes to be returned by read()."""
        with self._cond:
            self._recv_buf += data
            self._cond.notify_all()

    def inject_error(self, exc: Exception) -> None:
        """Cause the next read() to raise exc, simulating a broken connection."""
        with self._cond:
            self._error = exc
            self._cond.notify_all()

    def pop_sent(self) -> bytes:
        """Return and clear all bytes written by send()."""
        with self._cond:
            data = bytes(self._send_buf)
            self._send_buf.clear()
            return data


def _encode(payload: dict) -> bytes:
    """Build a framed DAP message from a dict."""
    content = json.dumps(payload, separators=(",", ":"))
    header = f"Content-Length: {len(content)}\r\n\r\n"
    return (header + content).encode("utf-8")


def _make_request(seq: int, command: str) -> Request:
    return Request(type=MessageType.REQUEST, seq=seq, command=command, arguments=None)


@unittest.skip("")
class TestDAPConnection(unittest.TestCase):
    def _null_handler(self) -> MessageHandler:
        return MessageHandler(
            on_response=lambda _: None,
            on_event=lambda _: None,
            on_reverse_request=lambda _: None,
        )

    def _start(
        self, handler: MessageHandler, transport: Optional[FakeTransport] = None
    ):
        """Start a DAPConnection in a background thread. Returns (conn, transport, thread)."""
        if transport is None:
            transport = FakeTransport()
        conn = DAPConnection(transport)
        t = threading.Thread(target=conn.start, args=[handler], daemon=True)
        t.start()
        return conn, transport, t

    # ------------------------------------------------------------------
    # encode_message
    # ------------------------------------------------------------------

    def test_encode_message_framing(self):
        payload = {"type": "request", "seq": 1, "command": "initialize"}
        data = DAPConnection.encode_message(payload)
        header, _, body = data.partition(b"\r\n\r\n")
        self.assertTrue(header.startswith(b"Content-Length:"))
        content_length = int(header.split(b":")[1].strip())
        self.assertEqual(content_length, len(body))
        self.assertEqual(json.loads(body), payload)

    def test_encode_message_round_trips(self):
        payload = {"nested": {"a": 1, "b": [1, 2, 3]}}
        _, _, body = DAPConnection.encode_message(payload).partition(b"\r\n\r\n")
        self.assertEqual(json.loads(body), payload)

    # ------------------------------------------------------------------
    # validate_response
    # ------------------------------------------------------------------

    def test_validate_response_ok(self):
        req = {"seq": 1, "command": "initialize"}
        resp = {"request_seq": 1, "command": "initialize"}
        DAPConnection.validate_response(req, resp)  # must not raise

    def test_validate_response_command_mismatch(self):
        req = {"seq": 1, "command": "initialize"}
        resp = {"request_seq": 1, "command": "launch"}
        with self.assertRaises(ValueError):
            DAPConnection.validate_response(req, resp)

    def test_validate_response_seq_mismatch(self):
        req = {"seq": 1, "command": "initialize"}
        resp = {"request_seq": 99, "command": "initialize"}
        with self.assertRaises(ValueError):
            DAPConnection.validate_response(req, resp)

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def test_routes_event_to_handler(self):
        done = threading.Event()
        events: List[RawMessage] = []

        def on_event(msg: RawMessage) -> None:
            events.append(msg)
            done.set()

        handler = MessageHandler(
            on_response=lambda _: None,
            on_event=on_event,
            on_reverse_request=lambda _: None,
        )
        conn, transport, t = self._start(handler)
        try:
            transport.inject(_encode({"type": "event", "seq": 1, "event": "stopped"}))
            self.assertTrue(done.wait(timeout=1.0), "event handler not called in time")
            self.assertEqual(events[0]["event"], "stopped")
        finally:
            conn.stop()
            t.join(timeout=1.0)

    def test_routes_multiple_events_in_order(self):
        count = [0]
        done = threading.Event()
        events: List[RawMessage] = []

        def on_event(msg: RawMessage) -> None:
            events.append(msg)
            count[0] += 1
            if count[0] == 2:
                done.set()

        handler = MessageHandler(
            on_response=lambda _: None,
            on_event=on_event,
            on_reverse_request=lambda _: None,
        )
        conn, transport, t = self._start(handler)
        try:
            msg1 = {"type": "event", "seq": 1, "event": "initialized"}
            msg2 = {"type": "event", "seq": 2, "event": "stopped"}
            transport.inject(_encode(msg1) + _encode(msg2))
            self.assertTrue(done.wait(timeout=1.0))
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["event"], "initialized")
            self.assertEqual(events[1]["event"], "stopped")
        finally:
            conn.stop()
            t.join(timeout=1.0)

    def test_routes_reverse_request_to_handler(self):
        done = threading.Event()
        requests: List[RawMessage] = []

        def on_reverse_request(msg: RawMessage) -> None:
            requests.append(msg)
            done.set()

        handler = MessageHandler(
            on_response=lambda _: None,
            on_event=lambda _: None,
            on_reverse_request=on_reverse_request,
        )
        conn, transport, t = self._start(handler)
        try:
            msg = {
                "type": "request",
                "seq": 3,
                "command": "runInTerminal",
                "arguments": {},
            }
            transport.inject(_encode(msg))
            self.assertTrue(done.wait(timeout=1.0))
            self.assertEqual(requests[0]["command"], "runInTerminal")
        finally:
            conn.stop()
            t.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Partial message accumulation
    # ------------------------------------------------------------------

    def test_partial_message_waits_for_remainder(self):
        done = threading.Event()
        received: List[RawMessage] = []

        def on_event(msg: RawMessage) -> None:
            received.append(msg)
            done.set()

        handler = MessageHandler(
            on_response=lambda _: None,
            on_event=on_event,
            on_reverse_request=lambda _: None,
        )
        conn, transport, t = self._start(handler)
        try:
            full = _encode({"type": "event", "seq": 1, "event": "stopped"})
            half = len(full) // 2
            transport.inject(full[:half])
            self.assertFalse(
                done.wait(timeout=0.05), "handler fired on incomplete message"
            )
            transport.inject(full[half:])
            self.assertTrue(
                done.wait(timeout=1.0), "handler not called after message was completed"
            )
            self.assertEqual(received[0]["event"], "stopped")
        finally:
            conn.stop()
            t.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Request / response lifecycle
    # ------------------------------------------------------------------

    def test_get_response_unknown_seq_raises(self):
        transport = FakeTransport()
        conn = DAPConnection(transport)
        with self.assertRaises(AssertionError):
            conn.get_response(99, timeout=0.1)

    def test_get_response_timeout(self):
        conn, transport, t = self._start(self._null_handler())
        try:
            conn.send_request(_make_request(1, "initialize"))
            with self.assertRaises(TimeoutError):
                conn.get_response(1, timeout=0.05)
        finally:
            conn.stop()
            t.join(timeout=1.0)

    def test_get_response_success(self):
        done = threading.Event()
        responses: List[RawMessage] = []

        def on_response(msg: RawMessage) -> None:
            responses.append(msg)
            done.set()

        handler = MessageHandler(
            on_response=on_response,
            on_event=lambda _: None,
            on_reverse_request=lambda _: None,
        )
        conn, transport, t = self._start(handler)
        try:
            conn.send_request(_make_request(1, "initialize"))
            response = {
                "type": "response",
                "seq": 2,
                "request_seq": 1,
                "command": "initialize",
                "success": True,
            }
            transport.inject(_encode(response))
            result = conn.get_response(1, timeout=1.0)
            self.assertEqual(result["command"], "initialize")
            self.assertTrue(result["success"])
            self.assertTrue(done.wait(timeout=1.0), "on_response handler not called")
        finally:
            conn.stop()
            t.join(timeout=1.0)

    def test_get_response_connection_error_raises_dap_error(self):
        conn, transport, t = self._start(self._null_handler())
        try:
            conn.send_request(_make_request(1, "launch"))
            transport.inject_error(OSError("connection reset"))
            with self.assertRaises(DAPError):
                conn.get_response(1, timeout=1.0)
        finally:
            conn.stop()
            t.join(timeout=1.0)

    def test_alive_after_start_dead_after_stop(self):
        conn, _, t = self._start(self._null_handler())
        try:
            deadline = time.monotonic() + 1.0
            while not conn.is_alive() and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertTrue(conn.is_alive())
        finally:
            conn.stop()
            t.join(timeout=1.0)
        self.assertFalse(conn.is_alive())

    def test_stop_closes_transport(self):
        conn, transport, t = self._start(self._null_handler())
        conn.stop()
        t.join(timeout=1.0)
        self.assertFalse(transport.is_alive)
