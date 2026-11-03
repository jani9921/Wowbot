"""World-socket stream framing, handshake tracking and decryption for one connection.

Wire format (both directions, after the ASCII banner line):
    frame = Size(u32 LE) | Tag(12) | body(Size)
    body  = opcode(u32 LE) | payload           (AES-256-GCM encrypted once Tag != 0)
Plain handshake frames carry an all-zero tag. A connection that is first seen
mid-stream (no banner, so no challenges) is never decrypted: it is marked
``UNSYNCED`` and the next connection is picked up from its first byte.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct
import zlib

from .world_crypto import (CLIENT_TO_SERVER, SERVER_TO_CLIENT, TAG_SIZE,
                           WorldPacketCipher, derive_encryption_key)

SERVER_BANNER = b"WORLD OF WARCRAFT CONNECTION - SERVER TO CLIENT - V2\n"
CLIENT_BANNER = b"WORLD OF WARCRAFT CONNECTION - CLIENT TO SERVER - V2\n"
HEADER_SIZE = 4 + TAG_SIZE
MAX_FRAME_SIZE = 0x10000
_ZERO_TAG = bytes(TAG_SIZE)

# connection states
WAITING = "WAITING_FOR_BANNER"
PLAIN = "PLAIN_HANDSHAKE"
ENCRYPTED = "ENCRYPTED_OK"
UNSYNCED = "UNSYNCED_MID_STREAM"
KEY_UNAVAILABLE = "KEY_UNAVAILABLE"
KEY_MISMATCH = "KEY_MISMATCH"
FRAME_ERROR = "FRAME_ERROR"


@dataclass(frozen=True)
class AuthOpcodes:
    """12.1.5 (70340 family) values; offsets are TrinityCore's field order."""
    auth_challenge: int = 0x4C0000
    auth_session: int = 0x440001
    auth_continued_session: int = 0x440003
    compressed_packet: int = 0x4C000E
    server_challenge_offset: int = 32      # DosChallenge[32] precedes Challenge[32]
    auth_session_challenge_offset: int = 20   # u64 + 3 x u32 precede LocalChallenge[32]
    continued_challenge_offset: int = 8       # u64 DosResponse precedes LocalChallenge[32]
    challenge_size: int = 32


@dataclass(frozen=True)
class WorldPacket:
    direction: str
    connection_index: int
    timestamp: float
    opcode: int
    payload: bytes
    encrypted: bool = False
    from_compressed: bool = False


class LoginSession:
    """Shared across the world connections of one client login.

    ``key_provider`` returns the 64-byte KeyData (read-only, in memory only). The
    40-byte session key derived on the first connection is reused by instance
    connections, exactly like the server does.
    """

    def __init__(self, key_provider):
        self._provider = key_provider
        self.session_key: bytes | None = None
        self.key_reads = 0

    def encryption_key_for_session(self, server_challenge: bytes, local_challenge: bytes) -> bytes:
        from .world_crypto import derive_session_key
        key_data = bytearray(self._provider())
        try:
            self.key_reads += 1
            self.session_key = derive_session_key(bytes(key_data), server_challenge, local_challenge)
        finally:
            for index in range(len(key_data)):
                key_data[index] = 0
        return derive_encryption_key(self.session_key, local_challenge, server_challenge)

    def encryption_key_for_continued(self, server_challenge: bytes, local_challenge: bytes) -> bytes:
        if self.session_key is None:
            raise LookupError("instance connection before the first authenticated connection")
        return derive_encryption_key(self.session_key, local_challenge, server_challenge)


class _Half:
    __slots__ = ("buffer", "banner_done")

    def __init__(self):
        self.buffer = bytearray()
        self.banner_done = False


class WorldConnection:
    def __init__(self, index: int, session: LoginSession, *, opcodes: AuthOpcodes | None = None):
        self.index = int(index)
        self.session = session
        self.opcodes = opcodes or AuthOpcodes()
        self.state = WAITING
        self.detail = ""
        self.cipher: WorldPacketCipher | None = None
        self.server_challenge: bytes | None = None
        self.packets = {CLIENT_TO_SERVER: 0, SERVER_TO_CLIENT: 0}
        self.tag_failures = 0
        self.decrypted = 0
        self.decompress_errors = 0
        self._half = {CLIENT_TO_SERVER: _Half(), SERVER_TO_CLIENT: _Half()}
        self._first_plain = {CLIENT_TO_SERVER: True, SERVER_TO_CLIENT: True}
        self._inflate = zlib.decompressobj()

    def snapshot(self) -> dict:
        return {"index": self.index, "state": self.state, "detail": self.detail,
                "packets_c2s": self.packets[CLIENT_TO_SERVER],
                "packets_s2c": self.packets[SERVER_TO_CLIENT],
                "decrypted": self.decrypted, "tag_failures": self.tag_failures,
                "counter_resyncs": self.cipher.resyncs if self.cipher else 0}

    def _fail(self, state: str, detail: str) -> None:
        self.state = state
        self.detail = detail
        for half in self._half.values():
            half.buffer.clear()

    def feed(self, direction: str, data: bytes, timestamp: float) -> list[WorldPacket]:
        direction = str(direction)
        if self.state in (UNSYNCED, FRAME_ERROR):
            return []
        half = self._half[direction]
        half.buffer.extend(data)
        banner = SERVER_BANNER if direction == SERVER_TO_CLIENT else CLIENT_BANNER
        if not half.banner_done:
            if len(half.buffer) < len(banner):
                if not banner.startswith(bytes(half.buffer)):
                    self._fail(UNSYNCED, "stream does not start with the world banner")
                return []
            if bytes(half.buffer[:len(banner)]) != banner:
                self._fail(UNSYNCED, "stream does not start with the world banner")
                return []
            del half.buffer[:len(banner)]
            half.banner_done = True
            if self.state == WAITING:
                self.state = PLAIN
        output: list[WorldPacket] = []
        while len(half.buffer) >= HEADER_SIZE:
            size = struct.unpack_from("<I", half.buffer, 0)[0]
            if size < 4 or size >= MAX_FRAME_SIZE:
                self._fail(FRAME_ERROR, f"invalid frame size {size}")
                return output
            total = HEADER_SIZE + size
            if len(half.buffer) < total:
                break
            tag = bytes(half.buffer[4:HEADER_SIZE])
            body = bytes(half.buffer[HEADER_SIZE:total])
            del half.buffer[:total]
            output.extend(self._frame(direction, tag, body, timestamp))
            if self.state in (FRAME_ERROR, UNSYNCED):
                break
        return output

    def _frame(self, direction: str, tag: bytes, body: bytes, timestamp: float) -> list[WorldPacket]:
        encrypted = tag != _ZERO_TAG
        if encrypted:
            if self.cipher is None:
                self.state, self.detail = KEY_UNAVAILABLE, "encrypted frame before key derivation"
                return []
            plain = self.cipher.decrypt(direction, tag, body)
            if plain is None:
                self.tag_failures += 1
                if self.decrypted == 0:
                    self.state = KEY_MISMATCH
                    self.detail = "first encrypted frame failed GCM authentication"
                return []
            self.decrypted += 1
            if self.state in (PLAIN, KEY_MISMATCH):
                self.state, self.detail = ENCRYPTED, ""
        else:
            plain = body
        opcode = struct.unpack_from("<I", plain, 0)[0]
        payload = plain[4:]
        self.packets[direction] += 1
        packet = WorldPacket(direction, self.index, timestamp, opcode, payload, encrypted)
        if not encrypted:
            self._handshake(direction, opcode, payload)
        result = [packet]
        if direction == SERVER_TO_CLIENT and opcode == self.opcodes.compressed_packet:
            inner = self._decompress(payload, timestamp)
            if inner is not None:
                result.append(inner)
        return result

    def _handshake(self, direction: str, opcode: int, payload: bytes) -> None:
        ids, size = self.opcodes, self.opcodes.challenge_size
        if direction == SERVER_TO_CLIENT and opcode == ids.auth_challenge:
            start = ids.server_challenge_offset
            if len(payload) >= start + size:
                self.server_challenge = payload[start:start + size]
            return
        if direction != CLIENT_TO_SERVER or self.server_challenge is None:
            return
        try:
            if opcode == ids.auth_session:
                start = ids.auth_session_challenge_offset
                local = payload[start:start + size]
                key = self.session.encryption_key_for_session(self.server_challenge, local)
            elif opcode == ids.auth_continued_session:
                start = ids.continued_challenge_offset
                local = payload[start:start + size]
                key = self.session.encryption_key_for_continued(self.server_challenge, local)
            else:
                return
            if len(local) != size:
                raise ValueError("truncated authentication packet")
        except Exception as error:  # noqa: BLE001 -- provider/derivation failure is state, not a crash
            self.state = KEY_UNAVAILABLE
            self.detail = f"{type(error).__name__}: {error}"
            return
        self.cipher = WorldPacketCipher(key)

    def _decompress(self, payload: bytes, timestamp: float) -> WorldPacket | None:
        try:
            uncompressed_size, _adler_plain, _adler_zip = struct.unpack_from("<III", payload, 0)
            data = self._inflate.decompress(payload[12:])
            if len(data) != uncompressed_size or len(data) < 4:
                raise ValueError("decompressed size mismatch")
            return WorldPacket(SERVER_TO_CLIENT, self.index, timestamp,
                               struct.unpack_from("<I", data, 0)[0], data[4:], True, True)
        except (struct.error, zlib.error, ValueError):
            self.decompress_errors += 1
            self._inflate = zlib.decompressobj()
            return None
