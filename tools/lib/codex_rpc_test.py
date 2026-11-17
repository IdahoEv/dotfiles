"""Wire-level tests for the local daemon transport."""

import json
import socket
import struct
import unittest
from unittest.mock import Mock

from codex_rpc import Daemon, RpcError


def frame(payload, opcode=1, final=True):
    header = bytes([(128 if final else 0) | opcode])
    size = len(payload)
    if size < 126:
        return header + bytes([size]) + payload
    return header + bytes([126]) + struct.pack("!H", size) + payload


class WireTests(unittest.TestCase):
    def setUp(self):
        self.client, self.server = socket.socketpair()
        self.addCleanup(self.client.close)
        self.addCleanup(self.server.close)
        self.rpc = Daemon(timeout=0.1)
        self.rpc.sock = self.client
        self.client.settimeout(0.1)

    def test_fragmented_response_with_interleaved_ping(self):
        payload = json.dumps({"id": 1, "result": {"ok": True}}).encode()
        self.server.sendall(frame(payload[:10], final=False) + frame(b"ping", 9) + frame(payload[10:], 0))
        self.assertEqual(self.rpc.receive()["result"], {"ok": True})
        pong = self.server.recv(100)
        self.assertEqual(pong[0], 138)

    def test_outgoing_frames_are_masked_at_each_length_boundary(self):
        self.rpc.sock = Mock()
        for size in (3, 126, 65536):
            with self.subTest(size=size):
                payload = b"a" * size
                self.rpc.frame(payload)
                data = self.rpc.sock.sendall.call_args.args[0]
                overhead = 6 if size < 126 else 8 if size < 65536 else 14
                self.assertEqual(len(data), size + overhead)
                self.assertEqual(data[0], 129)
                self.assertTrue(data[1] & 128)
                offset = overhead - 4
                mask = data[offset:offset+4]
                decoded = bytes(b ^ mask[i % 4] for i, b in enumerate(data[overhead:]))
                self.assertEqual(decoded, payload)

    def test_notifications_do_not_hide_rpc_error(self):
        self.server.sendall(frame(b'{"method":"thread/started","params":{}}') +
                            frame(b'{"id":1,"error":{"code":-32601,"message":"unsupported"}}'))
        with self.assertRaisesRegex(RpcError, "unsupported"):
            self.rpc.call("thread/start", {})

    def test_disconnect_is_an_error(self):
        self.server.close()
        with self.assertRaisesRegex(RpcError, "disconnected"):
            self.rpc.receive()

    def test_timeout_names_recovery_action(self):
        with self.assertRaisesRegex(RpcError, "inspect codex agents"):
            self.rpc.call("thread/start", {})

    def test_handshake_is_rejected_without_accept_header(self):
        self.server.sendall(b"HTTP/1.1 101 Switching Protocols\r\n\r\n")
        with self.assertRaisesRegex(RpcError, "handshake"):
            self.rpc.handshake()

    def test_server_request_is_never_auto_approved(self):
        self.server.sendall(frame(b'{"id":4,"method":"item/commandExecution/requestApproval"}'))
        with self.assertRaisesRegex(RpcError, "human input"):
            self.rpc.call("turn/start", {})


if __name__ == "__main__":
    unittest.main()
