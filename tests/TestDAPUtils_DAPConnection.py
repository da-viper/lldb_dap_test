import io
import json
import unittest
from typing import List

from lldb_dap.dap_types import RawMessage
from lldb_dap.utils import DAPConnection, MessageHandler, Transport


class EchoClient:
    def __init__(self):
        self.seen_messages: List[RawMessage] = []

    def on_message(self, msg: RawMessage):
        self.seen_messages.append(msg)


class TestDAPUtils_DAPConnection(unittest.TestCase):
    """Something"""

    def test_round_trip(self):
        received_messages = self.raw_data()
        transport = self.create_transport(received_messages)
        connection = DAPConnection(transport)

        client = EchoClient()
        handler = MessageHandler(
            on_event=client.on_message,
            on_response=client.on_message,
            on_reverse_request=client.on_message,
        )
        connection.start(handler)
        expected_messages = client.seen_messages
        self.assertEqual(len(received_messages), len(expected_messages))
        for actual, expected in zip(received_messages, expected_messages):
            self.assertEqual(actual, expected)

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

    def test_incomplete_message(self):
        # TODO:
        ...

    def test_eof(self):
        # TODO:
        ...

    @staticmethod
    def create_transport(data: List[RawMessage]) -> Transport:
        class BinaryTransport:
            def __init__(self, data: List[RawMessage]):
                encoded_data = [
                    DAPConnection.encode_message(message) for message in data
                ]
                self._in = io.BytesIO(b"".join(encoded_data))
                self._out: List[str] = []

            def write(self, data: bytes):
                self._out.append(data.decode("utf-8"))

            def readline(self):
                return self._in.readline()

            def read(self, n: int) -> bytes:
                return self._in.read(n)

            def close(self):
                self._in.close()

            @property
            def is_alive(self) -> bool:
                return not self._in.closed

        return BinaryTransport(data)

    def raw_data(self):
        # fmt: off
        raw_events = [
            {"body": {"category": "console", "output": "Running preInitCommands:\n"}, "event": "output", "seq": 2, "type": "event"},
            {"body": {"category": "console", "output": "(lldb) log enable lldb event -T -f dap_event.log\n"}, "event": "output", "seq": 3, "type": "event"},
            {"body": {"category": "console", "output": "To get started with the debug console try \"<variable>\", \"<lldb-cmd>\" or \"help [<lldb-cmd>]\"\r\n"}, "event": "output", "seq": 4, "type": "event"},
            {"body": {"category": "console", "output": "For more information visit https://lldb.llvm.org/use/lldbdap.html#debug-console.\r\n"}, "event": "output", "seq": 5, "type": "event"},
            {"body": {"module": {"addressRange": "0x7e4ec4e6e000", "debugInfoSize": "563.1KB", "id": "A55BBBD8-5660-8820-2DBB-60DA08A95C6B-7697E8EE", "name": "ld-linux-x86-64.so.2", "path": "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2", "symbolFilePath": "/usr/lib/debug/.build-id/a5/5bbbd8566088202dbb60da08a95c6b7697e8ee.debug", "symbolStatus": "Symbols loaded."}, "reason": "new"}, "event": "module", "seq": 6, "type": "event"},
        ]
        # fmt: on
        return raw_events
