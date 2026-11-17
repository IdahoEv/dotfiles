"""JSON-RPC over the local Codex daemon's Unix WebSocket."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import time


class RpcError(RuntimeError):
    pass


class Daemon:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout
        self.sock = None
        self.sequence = 0

    def __enter__(self):
        try:
            environment = {key: value for key, value in os.environ.items() if key != "MEM_GUARD_OVERRIDE"}
            result = subprocess.run(
                ["codex", "app-server", "daemon", "start"],
                env=environment, capture_output=True, text=True, timeout=self.timeout, check=True,
            )
            result = subprocess.run(
                ["codex", "app-server", "daemon", "version"],
                env=environment, capture_output=True, text=True, timeout=self.timeout, check=True,
            )
            info = json.loads(result.stdout)
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect(info["socketPath"])
            self.handshake()
            self.call("initialize", {
                "clientInfo": {"name": "dotfiles_codex", "version": "1"},
                "capabilities": {"experimentalApi": True},
            })
            self.send({"method": "initialized"})
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def exact(self, count):
        data = bytearray()
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise RpcError("Codex daemon disconnected")
            data.extend(chunk)
        return bytes(data)

    def handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        headers = bytearray()
        while not headers.endswith(b"\r\n\r\n"):
            headers.extend(self.exact(1))
            if len(headers) > 16384:
                raise RpcError("oversized WebSocket handshake")
        lines = headers.decode("ascii").split("\r\n")
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        ).digest()).decode()
        fields = {key.lower(): value.strip() for line in lines[1:] if ":" in line
                  for key, value in [line.split(":", 1)]}
        if " 101 " not in lines[0] or fields.get("sec-websocket-accept", "") != accept:
            raise RpcError("Codex daemon rejected the WebSocket handshake")

    def frame(self, payload, opcode=1):
        size = len(payload)
        header = bytes([0x80 | opcode])
        if size < 126:
            header += bytes([0x80 | size])
        elif size < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", size)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", size)
        mask = os.urandom(4)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, message):
        self.frame(json.dumps(message).encode())

    def receive(self):
        data = bytearray()
        while True:
            first, second = self.exact(2)
            opcode, size = first & 15, second & 127
            if size == 126:
                size = struct.unpack("!H", self.exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.exact(8))[0]
            if size + len(data) > 32 * 1024 * 1024:
                raise RpcError("oversized Codex response")
            if second & 128:
                raise RpcError("unexpected masked server frame")
            payload = self.exact(size)
            if opcode == 8:
                raise RpcError("Codex daemon closed the connection")
            if opcode == 9:
                self.frame(payload, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1):
                raise RpcError(f"unsupported WebSocket opcode {opcode}")
            data.extend(payload)
            if first & 128:
                return json.loads(data)

    def call(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        try:
            while time.monotonic() < deadline:
                self.sock.settimeout(max(0.01, deadline - time.monotonic()))
                message = self.receive()
                if "method" in message:
                    if "id" in message:
                        raise RpcError(
                            f"{method}: daemon requested {message['method']}; "
                            "open codex agents to handle human input"
                        )
                    continue
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise RpcError(f"{method}: {message['error']}")
                return message["result"]
            raise RpcError(f"{method}: response timed out")
        except TimeoutError as exc:
            raise RpcError(f"{method}: response timed out; inspect codex agents before retrying") from exc
