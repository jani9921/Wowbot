"""World-connection key derivation and AES-256-GCM packet crypto (Retail 12.x).

Pure functions and small stateful ciphers; no OS, process or network access.

Protocol facts were taken as a specification from TrinityCore's public
``WorldSocket.cpp`` / ``WorldPacketCrypt`` (GPL-2+) and re-implemented here in
independent code.  The four 32-byte seeds are the client's own constants; the
tests verify them byte-for-byte against the installed ``Wow.exe`` when present.
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

SERVER_IV_MAGIC = 0x52565253  # bytes "SRVR": server -> client packets
CLIENT_IV_MAGIC = 0x544E4C43  # bytes "CLNT": client -> server packets
TAG_SIZE = 12  # the header carries a 12-byte truncation of the 16-byte GCM tag
KEY_DATA_SIZE = 64
SESSION_KEY_SIZE = 40
ENCRYPT_KEY_SIZE = 32
SERVER_CHALLENGE_SIZE = 32


class SessionKeyGenerator:
    """Blizzard/TrinityCore session-key generator over SHA-512."""

    def __init__(self, data: bytes):
        half = len(data) // 2
        self._o1 = hashlib.sha512(data[:half]).digest()
        self._o2 = hashlib.sha512(data[half:]).digest()
        self._o0 = hashlib.sha512(self._o1 + bytes(64) + self._o2).digest()
        self._taken = 0

    def generate(self, size: int) -> bytes:
        out = bytearray()
        for _ in range(size):
            if self._taken == len(self._o0):
                self._o0 = hashlib.sha512(self._o1 + self._o0 + self._o2).digest()
                self._taken = 0
            out.append(self._o0[self._taken])
            self._taken += 1
        return bytes(out)


def derive_session_key(key_data: bytes, server_challenge: bytes, local_challenge: bytes) -> bytes:
    """40-byte session key from the 64-byte game-account key data."""
    key_hash = hashlib.sha512(key_data).digest()
    mac = hmac.new(key_hash, server_challenge + local_challenge + SESSION_KEY_SEED,
                   hashlib.sha512).digest()
    return SessionKeyGenerator(mac).generate(SESSION_KEY_SIZE)


def derive_encrypt_key(session_key: bytes, local_challenge: bytes, server_challenge: bytes) -> bytes:
    """32-byte AES-256 key; note the argument order differs from the session key."""
    mac = hmac.new(session_key, local_challenge + server_challenge + ENCRYPTION_KEY_SEED,
                   hashlib.sha512).digest()
    return mac[:ENCRYPT_KEY_SIZE]


def packet_iv(counter: int, magic: int) -> bytes:
    return struct.pack("<QI", counter, magic)


def gcm_seal(key: bytes, iv: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    ciphertext = cipher.encrypt(plaintext)
    return ciphertext, cipher.digest()[:TAG_SIZE]


def gcm_open(key: bytes, iv: bytes, ciphertext: bytes, tag: bytes) -> bytes | None:
    """Decrypt and verify the truncated tag; ``None`` when it does not verify."""
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    plaintext = cipher.decrypt(ciphertext)
    if not hmac.compare_digest(cipher.digest()[:TAG_SIZE], bytes(tag)):
        return None
    return plaintext


class PacketCipher:
    """One direction of one connection: key, IV magic and a packet counter."""

    def __init__(self, key: bytes, magic: int, counter: int = 0):
        if len(key) != ENCRYPT_KEY_SIZE:
            raise ValueError("AES-256 key must be 32 bytes")
        self.key = bytes(key)
        self.magic = int(magic)
        self.counter = int(counter)

    def seal(self, plaintext: bytes) -> tuple[bytes, bytes]:
        result = gcm_seal(self.key, packet_iv(self.counter, self.magic), plaintext)
        self.counter += 1
        return result

    def open(self, ciphertext: bytes, tag: bytes, *, search: int = 0) -> tuple[bytes, int] | None:
        """Verify with the expected counter, then up to ``search`` later ones.

        Returns ``(plaintext, skipped_packets)``; the counter is advanced past
        the matched packet.  Lost packets therefore resynchronise instead of
        silently producing garbage: only a verified tag is ever accepted.
        """
        for skipped in range(search + 1):
            plain = gcm_open(self.key, packet_iv(self.counter + skipped, self.magic),
                             ciphertext, tag)
            if plain is not None:
                self.counter += skipped + 1
                return plain, skipped
        return None
