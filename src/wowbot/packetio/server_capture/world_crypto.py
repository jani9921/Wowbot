"""Retail world-socket key derivation and AES-256-GCM packet crypto (12.1.x).

Written from the public TrinityCore protocol description (GPL spec only, no code
copied) and cross-checked against the client: all four 32-byte seeds below are
byte-identical to the constants in the installed Wow.exe 12.1.5.70575 ``.rdata``.

Derivation, per world connection:
    key_hash    = SHA512(KeyData[64])
    session_hmac= HMAC512(key_hash, serverChallenge || localChallenge || SESSION_KEY_SEED)
    session_key = SessionKeyGenerator512(session_hmac).generate(40)
    encrypt_key = HMAC512(session_key, localChallenge || serverChallenge
                          || ENCRYPTION_KEY_SEED)[:32]
Instance ("continued session") connections reuse ``session_key`` and only repeat
the last step with their own challenges.

Packets are AES-256-GCM with IV = counter(u64 LE) || magic(u32 LE), no AAD, and a
12-byte (truncated) tag carried in the frame header.
"""
from __future__ import annotations

import hashlib
import hmac
import struct

from Cryptodome.Cipher import AES

AUTH_CHECK_SEED = bytes.fromhex(
    "DE3A2A8E6B895266889D7E7A771D5D1F4ED90C239BCD0EDCD2E8043A6864C7B0")
SESSION_KEY_SEED = bytes.fromhex(
    "E81E8B5927621EAA861518EAC0BF668C6DBF8393BCAA80525B1EDC23A012B750")
CONTINUED_SESSION_SEED = bytes.fromhex(
    "565C619C483A521F615D0549B29A39BF4B97B01BF96CDED6801DAB2602A99B9D")
ENCRYPTION_KEY_SEED = bytes.fromhex(
    "71C9ED5AA70E4DFF4C36A65A3E468A4A5DA148C830474ADEF60D6CBE6FE45573")

CLIENT_TO_SERVER = "CLIENT_TO_SERVER"
SERVER_TO_CLIENT = "SERVER_TO_CLIENT"
_MAGIC = {CLIENT_TO_SERVER: 0x544E4C43, SERVER_TO_CLIENT: 0x52565253}
TAG_SIZE = 12
KEY_DATA_SIZE = 64
SESSION_KEY_SIZE = 40
ENCRYPTION_KEY_SIZE = 32


def _sha512(*parts: bytes) -> bytes:
    digest = hashlib.sha512()
    for part in parts:
        digest.update(part)
    return digest.digest()


def _hmac512(key: bytes, *parts: bytes) -> bytes:
    mac = hmac.new(key, digestmod=hashlib.sha512)
    for part in parts:
        mac.update(part)
    return mac.digest()


class SessionKeyGenerator512:
    """Blizzard's interleaved hash stream (o1/o2 half hashes, o0 chained)."""

    def __init__(self, data: bytes):
        half = len(data) // 2
        self._o1 = _sha512(data[:half])
        self._o2 = _sha512(data[half:])
        self._o0 = _sha512(self._o1, bytes(64), self._o2)
        self._taken = 0

    def generate(self, size: int) -> bytes:
        out = bytearray()
        for _ in range(size):
            if self._taken == len(self._o0):
                self._o0 = _sha512(self._o1, self._o0, self._o2)
                self._taken = 0
            out.append(self._o0[self._taken])
            self._taken += 1
        return bytes(out)


def derive_session_key(key_data: bytes, server_challenge: bytes, local_challenge: bytes) -> bytes:
    if len(key_data) != KEY_DATA_SIZE:
        raise ValueError(f"key data must be {KEY_DATA_SIZE} bytes")
    session_hmac = _hmac512(_sha512(key_data), server_challenge, local_challenge,
                            SESSION_KEY_SEED)
    return SessionKeyGenerator512(session_hmac).generate(SESSION_KEY_SIZE)


def derive_encryption_key(session_key: bytes, local_challenge: bytes,
                          server_challenge: bytes) -> bytes:
    return _hmac512(session_key, local_challenge, server_challenge,
                    ENCRYPTION_KEY_SEED)[:ENCRYPTION_KEY_SIZE]


class WorldPacketCipher:
    """Per-connection AES-256-GCM state with an independent counter per direction.

    ``decrypt`` never advances a counter on failure, so a corrupt or foreign frame
    cannot desynchronise the stream; ``max_resync`` tolerates frames lost by the
    capture (the counter is then re-aligned on the first authenticated frame).
    """

    def __init__(self, key: bytes, *, max_resync: int = 16):
        if len(key) != ENCRYPTION_KEY_SIZE:
            raise ValueError(f"encryption key must be {ENCRYPTION_KEY_SIZE} bytes")
        self._key = bytes(key)
        self._counters = {CLIENT_TO_SERVER: 0, SERVER_TO_CLIENT: 0}
        self.max_resync = max(0, int(max_resync))
        self.resyncs = 0

    def counter(self, direction: str) -> int:
        return self._counters[str(direction)]

    def _process(self, direction: str, counter: int, data: bytes) -> tuple[bytes, bytes]:
        nonce = struct.pack("<QI", counter, _MAGIC[direction])
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        return cipher.decrypt(data), cipher.digest()[:TAG_SIZE]

    def decrypt(self, direction: str, tag: bytes, ciphertext: bytes) -> bytes | None:
        direction = str(direction)
        base = self._counters[direction]
        for step in range(self.max_resync + 1):
            plain, expected = self._process(direction, base + step, ciphertext)
            if hmac.compare_digest(expected, tag):
                if step:
                    self.resyncs += 1
                self._counters[direction] = base + step + 1
                return plain
        return None

    def encrypt(self, direction: str, plaintext: bytes) -> tuple[bytes, bytes]:
        """Test/replay helper: returns (tag, ciphertext) and advances the counter."""
        direction = str(direction)
        nonce = struct.pack("<QI", self._counters[direction], _MAGIC[direction])
        cipher = AES.new(self._key, AES.MODE_GCM, nonce=nonce)
        ciphertext = cipher.encrypt(plaintext)
        self._counters[direction] += 1
        return cipher.digest()[:TAG_SIZE], ciphertext
