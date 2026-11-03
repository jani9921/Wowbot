"""Automatic Wow.exe discovery and Ymir-equivalent read-only key acquisition.

Scope is deliberately identical to the pinned Ymir: for an exe whose SHA-256 is in
``PINNED`` the code reads (PROCESS_VM_READ only, never writes):
    qword[base + root_rva] -> P, then 64 bytes at P+8     (KeyData)
    int32[base + selector_rva] and qword[base + table_rva + 8*selector] -> 4 chars
The key never leaves memory: ``SessionMaterial`` redacts it in repr/str and is
zeroised by ``wipe``. Unknown builds are refused with an instruction instead of
guessing addresses; finding new addresses is a separate, user-run development
step (see docs/AGENT_SERVER_CAPTURE.md).
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import struct
import threading

KEY_DATA_SIZE = 64
LOCALE_COUNT = 12


@dataclass(frozen=True)
class ClientProfile:
    build: int
    exe_sha256: str
    root_rva: int
    selector_rva: int
    table_rva: int
    note: str = ""


PINNED: dict[int, ClientProfile] = {
    70575: ClientProfile(
        70575, "14b70997cf6c7971a4fcd533b7f421316b6a3da0c8da3710425a8dd20e356a29",
        0x4A50750, 0x49F4198, 0x3AF06E0, "user-run capture with the V3 Ymir decoded cleanly"),
    70448: ClientProfile(
        70448, "1c51e68c00e7183c2c187606d2c443c27252a629406454de4afec336e8c5753a",
        0x4ADF710, 0x4A83198, 0x3B7E6D0, "live-validated Ymir V2 values"),
}


class SessionMaterial:
    """KeyData + locale. The key is held in a bytearray and never printed."""

    def __init__(self, key_data: bytes, locale: str):
        self._key = bytearray(key_data)
        self.locale = locale

    def key_data(self) -> bytes:
        return bytes(self._key)

    def wipe(self) -> None:
        for index in range(len(self._key)):
            self._key[index] = 0

    def __repr__(self) -> str:
        return f"SessionMaterial(key=<redacted {len(self._key)} bytes>, locale={self.locale!r})"

    __str__ = __repr__


@dataclass
class WowProcess:
    pid: int
    exe: Path
    create_time: float
    profile: ClientProfile | None
    sha256: str = ""
    established: int = 0


_hash_cache: dict[tuple[str, int, int], str] = {}
_hash_lock = threading.Lock()


def exe_sha256(path: Path) -> str:
    stat = Path(path).stat()
    key = (str(path), stat.st_size, int(stat.st_mtime))
    with _hash_lock:
        cached = _hash_cache.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    with _hash_lock:
        _hash_cache[key] = digest.hexdigest()
    return digest.hexdigest()


def profile_for_hash(sha256: str) -> ClientProfile | None:
    for profile in PINNED.values():
        if profile.exe_sha256 == sha256.lower():
            return profile
    return None


def find_wow_processes(process_iter=None) -> list[WowProcess]:
    """Every running retail Wow.exe, best candidate first.

    Order: pinned build first, then one with ESTABLISHED TCP connections, then the
    newest. The caller never has to pick a PID; an ambiguous multi-client machine
    simply gets the best-ranked instance (``--pid`` can still force one).
    """
    import psutil
    found: list[WowProcess] = []
    for process in (process_iter or psutil.process_iter)(["pid", "name", "exe", "create_time"]):
        info = process.info
        if (info.get("name") or "").lower() != "wow.exe" or not info.get("exe"):
            continue
        exe = Path(info["exe"])
        try:
            sha = exe_sha256(exe)
        except OSError:
            continue
        item = WowProcess(int(info["pid"]), exe, float(info.get("create_time") or 0.),
                          profile_for_hash(sha), sha)
        try:
            item.established = sum(1 for c in process.net_connections(kind="tcp")
                                   if c.status == "ESTABLISHED")
        except Exception:  # noqa: BLE001 -- access denied is not fatal for ranking
            item.established = 0
        found.append(item)
    found.sort(key=lambda p: (p.profile is None, p.established == 0, -p.create_time))
    return found


# --------------------------------------------------------------------- memory access
_PROCESS_VM_READ = 0x0010
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPMODULE, _TH32CS_SNAPMODULE32 = 0x8, 0x10


class _MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD), ("hModule", wintypes.HMODULE),
        ("szModule", wintypes.WCHAR * 256), ("szExePath", wintypes.WCHAR * 260),
    ]


class ProcessReader:
    """PROCESS_VM_READ-only handle with a bounded read primitive."""

    def __init__(self, pid: int):
        if os.name != "nt":
            raise OSError("process reading is Windows-only")
        self.pid = int(pid)
        self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._k32.OpenProcess.restype = wintypes.HANDLE
        self._k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self._k32.Module32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MODULEENTRY32W)]
        self._k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self._handle = self._k32.OpenProcess(
            _PROCESS_VM_READ | _PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error(), "OpenProcess")
        self.base = self._module_base()

    def _module_base(self) -> int:
        invalid = ctypes.c_void_p(-1).value
        snapshot = self._k32.CreateToolhelp32Snapshot(
            _TH32CS_SNAPMODULE | _TH32CS_SNAPMODULE32, self.pid)
        if snapshot == invalid:
            raise ctypes.WinError(ctypes.get_last_error(), "CreateToolhelp32Snapshot")
        try:
            entry = _MODULEENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            if not self._k32.Module32FirstW(snapshot, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error(), "Module32FirstW")
            return int(ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value)
        finally:
            self._k32.CloseHandle(snapshot)

    def read(self, address: int, size: int) -> bytes:
        buffer = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        if not self._k32.ReadProcessMemory(self._handle, ctypes.c_void_p(address), buffer, size,
                                           ctypes.byref(got)) or got.value != size:
            raise OSError(f"cannot read {size} bytes at {address:#x}")
        return bytes(buffer)

    def close(self) -> None:
        if self._handle:
            self._k32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def read_session_material(read, base: int, profile: ClientProfile) -> SessionMaterial:
    """Pure over ``read(address, size)`` so it is testable without a process."""
    root = struct.unpack("<Q", read(base + profile.root_rva, 8))[0]
    if not 0x10000 <= root < 0x7FF000000000:
        raise LookupError("capture root is empty (no authenticated session yet)")
    key = read(root + 8, KEY_DATA_SIZE)
    if not any(key):
        raise LookupError("session key block is all zero (no authenticated session yet)")
    locale = "enUS"
    try:
        selector = struct.unpack("<i", read(base + profile.selector_rva, 4))[0]
        if 0 <= selector < LOCALE_COUNT:
            slot = struct.unpack("<Q", read(base + profile.table_rva + selector * 8, 8))[0]
            text = read(slot, 4).decode("ascii")
            if text.isalpha():
                locale = text
    except (OSError, UnicodeDecodeError, struct.error):
        pass
    return SessionMaterial(key, locale)


def read_session_material_for_pid(pid: int, profile: ClientProfile) -> SessionMaterial:
    with ProcessReader(pid) as reader:
        return read_session_material(reader.read, reader.base, profile)
