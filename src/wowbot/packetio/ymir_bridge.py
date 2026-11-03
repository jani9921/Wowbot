"""Lifecycle-owned bridge for the one hash-pinned Retail 70575 Ymir binary.

Ymir may read the client's session/decryption key under the narrow exception in
AGENTS.md.  This module never reads game memory itself and never forwards keys,
raw packet bodies, authentication data, chat or personal fields.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import threading
import time

from .forwarder import (CompositeSink, EventPolicy, JsonlEventRecorder, SnapshotReplayForwarder,
                        UdpJsonForwarder)
from .pkt import OpcodeManifest, PktEventDecoder, PktFileFollower, PktFormatError


# User 2026-10-25: the client is 70575; the user's V3 port candidate replaces
# the 70448 V2 (f685d3d9...).  Its user-run 70575 dump decoded cleanly offline.
VALIDATED_SHA256 = "77cc8a63b94ee52c47090290a69f3d6fa3db3995ded3c7534c886c85dcbec6b9"
EXPECTED_BUILD = 70575
_PID_RE = re.compile(
    r"Automatically selected process:\s*.*?\(PID:\s*(\d+)\)", re.I)
_BUILD_RE = re.compile(r"Allowed build:\s*[0-9.]+\.(\d+)\s*$", re.I)
_DUMP_RE = re.compile(r"Writing dump to\s+(.+?\.pkt)\s*$", re.I)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_console_line(line):
    match = _PID_RE.search(line)
    if match:
        return "selected_pid", int(match.group(1))
    match = _BUILD_RE.search(line)
    if match:
        return "allowed_build", int(match.group(1))
    match = _DUMP_RE.search(line)
    if match:
        return "dump_path", match.group(1).strip().strip('"')
    return None


class YmirAgentBridge:
    """Start, scope and stop Ymir with the connected runtime's lifecycle."""

    def __init__(self, *, executable, output, selected_pid=None, endpoint_path=None):
        self.executable = Path(executable).resolve()
        self.selected_pid = int(selected_pid) if selected_pid is not None else None
        self.endpoint_path = (Path(endpoint_path).resolve()
                              if endpoint_path is not None else None)
        self.output = Path(output).resolve()
        self.status_path = self.output/"ymir_status.json"
        self.events_path = self.output/"ymir_events.jsonl"
        self.console_path = self.output/"ymir_console.jsonl"
        self.stop = threading.Event()
        self.monitor_stop = threading.Event()
        self.process = None
        self.follower = None
        self.stream_thread = None
        self._stream_starting = False
        self.pending_dump_path = None
        self._lock = threading.RLock()
        self._state = {"schema": "aipc.ymir-bridge-status.v1", "state": "STARTING",
            "requested_pid": self.selected_pid, "detected_pid": None,
            "pid_verified": False, "build_verified": False,
            "expected_build": EXPECTED_BUILD, "dump_path": None,
            "records": 0, "semantic_events": 0, "forwarded_events": 0,
            "last_semantic_event": None, "error": None}

    def _set(self, **values):
        with self._lock:
            self._state.update(values)
            self._state["updated_at"] = time.time()

    def snapshot(self):
        with self._lock:
            value = dict(self._state)
        if self.follower is not None:
            value["pkt"] = self.follower.snapshot()
        return value

    def _write_status(self):
        from adapters.atomic_file import write_json_replace
        write_json_replace(self.status_path, self.snapshot())

    def _monitor(self):
        while not self.monitor_stop.wait(.5):
            self._write_status()
        self._write_status()

    def validate(self):
        if self.selected_pid is not None and self.selected_pid <= 0:
            raise ValueError("positive selected PID required")
        if not self.executable.is_file():
            raise FileNotFoundError(f"pinned Ymir executable missing: {self.executable}")
        if sha256_file(self.executable).lower() != VALIDATED_SHA256:
            raise ValueError("refusing unvalidated Ymir executable: SHA-256 mismatch")

    def bind(self, *, selected_pid, endpoint_path):
        """Bind the already-listening capture to one authoritative GUI PID."""
        selected_pid = int(selected_pid)
        if selected_pid <= 0:
            raise ValueError("positive selected PID required")
        endpoint_path = Path(endpoint_path).resolve()
        with self._lock:
            detected = self._state.get("detected_pid")
            previous = self.selected_pid
            if previous is not None and previous != selected_pid:
                raise RuntimeError(
                    f"Ymir is already bound to PID {previous}; requested {selected_pid}")
            if detected is not None and detected != selected_pid:
                raise RuntimeError(
                    f"Ymir detected PID {detected}; authoritative GUI PID is {selected_pid}")
            self.selected_pid = selected_pid
            self.endpoint_path = endpoint_path
            self._state["requested_pid"] = selected_pid
            self._state["endpoint_path"] = str(endpoint_path)
            self._state["updated_at"] = time.time()
        self._try_start_stream()

    def _try_start_stream(self):
        with self._lock:
            path = self.pending_dump_path
            ready = (path is not None and self.selected_pid is not None
                     and self.endpoint_path is not None
                     and self._state.get("pid_verified")
                     and self._state.get("build_verified"))
            if not ready or self.stream_thread is not None or self._stream_starting:
                return
            self._stream_starting = True
        try:
            self._start_stream(path)
        finally:
            with self._lock:
                self._stream_starting = False

    def request_stop(self):
        if self.snapshot().get("error") is None:
            self._set(state="STOPPING")
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError, ValueError):
                process.terminate()

    def force_stop(self):
        self.stop.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()

    def _stream(self, path):
        from .process_identity import selected_process_identity
        try:
            process_identity = selected_process_identity(self.selected_pid)
        except (OSError, ValueError, AttributeError):
            self._set(state="ERROR", error="selected_process_generation_unavailable")
            self.stop.set()
            return
        udp = UdpJsonForwarder(policy=EventPolicy(), descriptor_path=self.endpoint_path,
                               process_generation=process_identity.generation)
        recorder = JsonlEventRecorder(self.events_path, policy=EventPolicy(allow_unknown=True))
        # Login creates arrive before the runtime's packet context exists;
        # each new context first receives the current entity snapshot.
        replay = SnapshotReplayForwarder(udp)
        sink = CompositeSink(replay, recorder)
        self.follower = PktFileFollower(path)
        decoder = header_seen = None
        from .stream_progress import CaptureProgress
        progress = CaptureProgress()
        try:
            self._set(state="WAITING_FOR_PKT_FILE")
            while not self.stop.is_set() and not Path(path).is_file():
                self.stop.wait(.05)
            if self.stop.is_set():
                return
            self._set(state="WAITING_FOR_PKT_DATA")
            for record in self.follower.records(self.stop):
                if decoder is None or self.follower.parser.header is not header_seen:
                    header = self.follower.parser.header
                    if decoder is not None:
                        replay.reset_capture()
                        progress=CaptureProgress()
                    if header.game_build != EXPECTED_BUILD:
                        raise PktFormatError(
                            f"PKT build {header.game_build} does not match {EXPECTED_BUILD}")
                    if header.game_build != process_identity.game_build:
                        raise PktFormatError('PKT build differs from selected executable metadata')
                    created_wall = int(process_identity.generation, 16)/10_000_000.-11644473600.
                    if header.start_unix_seconds+2. < created_wall:
                        raise PktFormatError('PKT archive predates the selected process lifetime')
                    decoder = PktEventDecoder(selected_pid=self.selected_pid, header=header,
                                              manifest=OpcodeManifest.reviewed(header.game_build),
                                              process_generation=process_identity.generation)
                    header_seen=header
                    self._set(state="STREAMING", game_build=header.game_build)
                epoch = decoder.capture_epoch
                events = decoder.decode_all(record)
                if decoder.capture_epoch != epoch:
                    replay.reset_capture()
                    progress=CaptureProgress()
                with self._lock:
                    self._state["records"] = int(self._state["records"])+1
                for event in events:
                    before = udp.sent
                    sink.emit(event)
                    if event.semantic_status == "CONFIRMED":
                        with self._lock:
                            self._state["semantic_events"] = int(
                                self._state["semantic_events"])+1
                            self._state["last_semantic_event"] = event.event_type
                            self._state["forwarded_events"] = int(
                                self._state["forwarded_events"])+(udp.sent-before)
                before = udp.sent
                sink.flush()  # paced snapshot also advances on records with no semantic event
                witness=progress.note(record,decoder)
                if witness is not None:
                    udp.emit_progress(witness)
                with self._lock:
                    self._state["forwarded_events"] = int(self._state["forwarded_events"])+(udp.sent-before)
        except Exception as error:
            self._set(state="ERROR", error=f"{type(error).__name__}: {error}")
            self.stop.set()
        finally:
            sink.close()

    def _start_stream(self, text):
        if self.stream_thread is not None:
            raise RuntimeError("multiple PKT archives announced in one Ymir session")
        path = Path(text)
        if not path.is_absolute():
            path = (self.executable.parent/path).resolve()
        self._set(state="WAITING_FOR_PKT_FILE", dump_path=str(path))
        self.stream_thread = threading.Thread(target=self._stream, args=(path,),
                                              name="aipc-ymir-pkt", daemon=True)
        self.stream_thread.start()

    def _drain(self, timeout=5.):
        if self.stream_thread is None or self.follower is None:
            return
        deadline, previous, stable = time.monotonic()+timeout, None, 0
        while time.monotonic() < deadline:
            snap = self.follower.snapshot()
            size = Path(snap["path"]).stat().st_size if Path(snap["path"]).is_file() else None
            current = (size, snap["bytes_read"], snap["buffered_bytes"])
            if current == previous and size == snap["bytes_read"]:
                stable += 1
                if stable >= 4:
                    break
            else:
                stable = 0
            previous = current
            time.sleep(.1)
        self.stop.set()
        self.stream_thread.join(timeout=2.)

    def run(self):
        try:
            self.validate()
        except Exception as error:
            self._set(state="ERROR", error=f"{type(error).__name__}: {error}")
            self.output.mkdir(parents=True, exist_ok=True)
            self._write_status()
            return 2
        self.output.mkdir(parents=True, exist_ok=True)
        monitor = threading.Thread(target=self._monitor, name="aipc-ymir-status", daemon=True)
        monitor.start()
        code = 1
        try:
            self.process = subprocess.Popen([str(self.executable), "--packetlog"],
                cwd=str(self.executable.parent), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                bufsize=1, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            self._set(state="WAITING_FOR_PID")
            with self.console_path.open("a", encoding="utf-8", buffering=1) as console:
                for raw in self.process.stdout:
                    line = raw.rstrip("\r\n")
                    console.write(json.dumps({"timestamp": time.time(), "text": line},
                                             ensure_ascii=False)+"\n")
                    parsed = parse_console_line(line)
                    if parsed is None:
                        continue
                    kind, value = parsed
                    if kind == "allowed_build":
                        if value != EXPECTED_BUILD:
                            raise RuntimeError(f"Ymir build {value}, required {EXPECTED_BUILD}")
                        self._set(build_verified=True)
                        self._try_start_stream()
                    elif kind == "selected_pid":
                        if self.selected_pid is not None and value != self.selected_pid:
                            raise RuntimeError(
                                f"Ymir selected PID {value}, authoritative PID {self.selected_pid}")
                        self._set(pid_verified=True, detected_pid=value,
                                  state="WAITING_FOR_CONNECTION")
                        self._try_start_stream()
                    elif kind == "dump_path":
                        with self._lock:
                            self.pending_dump_path = value
                            self._state["dump_path"] = value
                            if self.selected_pid is None or self.endpoint_path is None:
                                self._state["state"] = "WAITING_FOR_AGENT_BIND"
                        self._try_start_stream()
            code = self.process.wait()
            self._drain()
            if self.snapshot().get("error") is None:
                self._set(state="STOPPED", ymir_exit_code=code)
        except Exception as error:
            self._set(state="ERROR", error=f"{type(error).__name__}: {error}")
            self.stop.set()
            self.request_stop()
        finally:
            self.stop.set()
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
            self.monitor_stop.set()
            monitor.join(timeout=1.)
        return code if self.snapshot().get("error") is None else 2
