from __future__ import annotations

import ctypes
from ctypes import POINTER, Structure, byref, c_char_p, c_int, c_long, c_uint, c_ubyte, c_void_p
from dataclasses import dataclass
import os
from pathlib import Path
import threading
import time
from typing import Iterator

from .models import RawPacket


PCAP_ERRBUF_SIZE = 256


class NpcapUnavailable(RuntimeError):
    pass


class _Timeval(Structure):
    _fields_ = [("tv_sec", c_long), ("tv_usec", c_long)]


class _PcapHeader(Structure):
    _fields_ = [("ts", _Timeval), ("caplen", c_uint), ("len", c_uint)]


class _PcapIf(Structure):
    pass


_PcapIf._fields_ = [
    ("next", POINTER(_PcapIf)),
    ("name", c_char_p),
    ("description", c_char_p),
    ("addresses", c_void_p),
    ("flags", c_uint),
]


class _BpfInsn(Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", c_ubyte), ("jf", c_ubyte), ("k", c_uint)]


class _BpfProgram(Structure):
    _fields_ = [("bf_len", c_uint), ("bf_insns", POINTER(_BpfInsn))]


@dataclass(frozen=True)
class CaptureInterface:
    name: str
    description: str
    flags: int


class _NpcapApi:
    def __init__(self, dll_path: str | Path | None = None):
        if os.name != "nt":
            raise NpcapUnavailable("Npcap capture is Windows-only")
        default_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "Npcap"
        path = Path(dll_path) if dll_path else default_dir / "wpcap.dll"
        if not path.exists():
            raise NpcapUnavailable(
                f"Npcap wpcap.dll not found at {path}. Install Npcap in WinPcap-compatible mode."
            )
        self._dll_directory = os.add_dll_directory(str(path.parent)) if hasattr(os, "add_dll_directory") else None
        self.lib = ctypes.CDLL(str(path))  # libpcap C calling convention, including 32-bit Python
        self.lib.pcap_findalldevs.argtypes = [POINTER(POINTER(_PcapIf)), c_char_p]
        self.lib.pcap_findalldevs.restype = c_int
        self.lib.pcap_freealldevs.argtypes = [POINTER(_PcapIf)]
        self.lib.pcap_open_live.argtypes = [c_char_p, c_int, c_int, c_int, c_char_p]
        self.lib.pcap_open_live.restype = c_void_p
        self.lib.pcap_datalink.argtypes = [c_void_p]
        self.lib.pcap_datalink.restype = c_int
        self.lib.pcap_next_ex.argtypes = [c_void_p, POINTER(POINTER(_PcapHeader)), POINTER(POINTER(c_ubyte))]
        self.lib.pcap_next_ex.restype = c_int
        self.lib.pcap_compile.argtypes = [c_void_p, POINTER(_BpfProgram), c_char_p, c_int, c_uint]
        self.lib.pcap_compile.restype = c_int
        self.lib.pcap_setfilter.argtypes = [c_void_p, POINTER(_BpfProgram)]
        self.lib.pcap_setfilter.restype = c_int
        self.lib.pcap_freecode.argtypes = [POINTER(_BpfProgram)]
        self.lib.pcap_geterr.argtypes = [c_void_p]
        self.lib.pcap_geterr.restype = c_char_p
        self.lib.pcap_close.argtypes = [c_void_p]
        self.lib.pcap_close.restype = None
        self.lib.pcap_setnonblock.argtypes = [c_void_p, c_int, c_char_p]
        self.lib.pcap_setnonblock.restype = c_int

    @staticmethod
    def _text(value: bytes | None) -> str:
        return value.decode("utf-8", "replace") if value else ""

    def interfaces(self) -> list[CaptureInterface]:
        devices = POINTER(_PcapIf)()
        error = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        if self.lib.pcap_findalldevs(byref(devices), error) != 0:
            raise NpcapUnavailable(self._text(error.value) or "pcap_findalldevs failed")
        result: list[CaptureInterface] = []
        try:
            current = devices
            while current:
                item = current.contents
                result.append(CaptureInterface(self._text(item.name), self._text(item.description), int(item.flags)))
                current = item.next
        finally:
            if devices:
                self.lib.pcap_freealldevs(devices)
        return result

    def error(self, handle) -> str:
        return self._text(self.lib.pcap_geterr(handle))


class NpcapCapture:
    """Read-only Npcap source. It never opens or writes a client process."""

    def __init__(
        self,
        interface: str,
        *,
        bpf_filter: str = "tcp",
        snap_length: int = 262144,
        timeout_ms: int = 50,
        promiscuous: bool = False,
        dll_path: str | Path | None = None,
    ):
        self.api = _NpcapApi(dll_path)
        self.interface = self._resolve_interface(interface)
        self.bpf_filter = str(bpf_filter)
        self.snap_length = int(snap_length)
        self.timeout_ms = int(timeout_ms)
        self.promiscuous = bool(promiscuous)
        self.handle = None
        self.link_type = -1
        self._closed = threading.Event()
        self._handle_lock = threading.Lock()

    @classmethod
    def list_interfaces(cls, dll_path: str | Path | None = None) -> list[CaptureInterface]:
        return _NpcapApi(dll_path).interfaces()

    def _resolve_interface(self, selector: str) -> CaptureInterface:
        interfaces = self.api.interfaces()
        exact = [item for item in interfaces if item.name == selector]
        if exact:
            return exact[0]
        token = selector.casefold()
        matches = [item for item in interfaces if token in item.name.casefold() or token in item.description.casefold()]
        if len(matches) != 1:
            choices = ", ".join(f"{item.name} ({item.description})" for item in interfaces)
            raise ValueError(f"capture interface must match exactly one device; matches={len(matches)}; available={choices}")
        return matches[0]

    def open(self) -> None:
        if self.handle:
            return
        error = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        handle = self.api.lib.pcap_open_live(
            self.interface.name.encode(), self.snap_length, int(self.promiscuous), self.timeout_ms, error
        )
        if not handle:
            raise NpcapUnavailable(self.api._text(error.value) or "pcap_open_live failed")
        program = _BpfProgram()
        try:
            if self.api.lib.pcap_compile(handle, byref(program), self.bpf_filter.encode("ascii"), 1, 0xFFFFFFFF) != 0:
                raise NpcapUnavailable(f"invalid capture filter: {self.api.error(handle)}")
            if self.api.lib.pcap_setfilter(handle, byref(program)) != 0:
                raise NpcapUnavailable(f"cannot install capture filter: {self.api.error(handle)}")
            if self.api.lib.pcap_setnonblock(handle, 1, error) != 0:
                raise NpcapUnavailable("cannot configure bounded non-blocking capture")
        except Exception:
            self.api.lib.pcap_close(handle)
            raise
        finally:
            if program.bf_insns:
                self.api.lib.pcap_freecode(byref(program))
        self.handle = handle
        self.link_type = int(self.api.lib.pcap_datalink(handle))

    def packets(self, stop: threading.Event | None = None) -> Iterator[RawPacket]:
        self.open()
        stop = stop or self._closed
        header = POINTER(_PcapHeader)()
        data = POINTER(c_ubyte)()
        while not stop.is_set() and not self._closed.is_set():
            with self._handle_lock:
                if not self.handle:
                    break
                status = self.api.lib.pcap_next_ex(self.handle, byref(header), byref(data))
                if status == 1:
                    value = header.contents
                    if value.caplen > self.snap_length:
                        raise NpcapUnavailable("captured packet exceeds configured snap length")
                    payload = ctypes.string_at(data, value.caplen)
                    seconds, micros = int(value.ts.tv_sec), int(value.ts.tv_usec)
                    captured_length, original_length = int(value.caplen), int(value.len)
            if status == 0:
                stop.wait(.005)
                continue
            if status == -2:
                break
            if status < 0:
                raise NpcapUnavailable("pcap_next_ex failed")
            yield RawPacket(
                captured_at=float(seconds) + float(micros) / 1_000_000.0,
                link_type=self.link_type,
                payload=payload,
                interface=self.interface.name,
                captured_length=captured_length,
                original_length=original_length,
            )

    def close(self) -> None:
        self._closed.set()
        with self._handle_lock:
            if self.handle:
                self.api.lib.pcap_close(self.handle)
                self.handle = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()
