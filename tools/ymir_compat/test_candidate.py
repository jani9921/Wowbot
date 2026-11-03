"""User-run, PID-scoped, bounded capture test; NEVER starts GUI/FULL_AI.

Only executable metadata is queried by this wrapper. The candidate retains the
existing Ymir capture implementation. Console output is allowlisted; packet
payloads are not printed or forwarded. Dumps remain private local test files.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"src"))
from wowbot.packetio.ymir_bridge import parse_console_line
from wowbot.packetio.pkt import PktV31StreamParser, OpcodeManifest

EXPECTED_BUILD = 70575
CLIENT_SHA256 = "14b70997cf6c7971a4fcd533b7f421316b6a3da0c8da3710425a8dd20e356a29"
CANDIDATE_SHA256 = "68a8ad1b7927c22e7911cb88d28f72f91f32ea73fddcdb1a40bc61a001f1ca5d"
CANDIDATE = ROOT/"runtime/ymir/candidates/70575/ymir_retail_12.1.5.70575_PORT_CANDIDATE.exe"


def process_list() -> list[tuple[str, int]]:
    result = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH"],
                            check=True, capture_output=True, text=True)
    return [(row[0], int(row[1])) for row in csv.reader(result.stdout.splitlines())
            if len(row) >= 2 and row[1].isdigit()]


def check_client(pid: int) -> None:
    if type(pid) is not int or pid <= 0:
        raise ValueError("positive, explicitly selected PID required")
    # PID is a validated integer; no command line, window title or memory read.
    command = (f"$p = Get-Process -Id {pid} -ErrorAction Stop; "
               "[pscustomobject]@{name=$p.ProcessName; path=$p.Path; "
               "version=$p.MainModule.FileVersionInfo.FileVersion} | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            check=True, capture_output=True, text=True)
    info = json.loads(result.stdout)
    if info["name"].lower() != "wow" or info["version"] != "12.1.5.70575":
        raise ValueError("selected process is not the reviewed Retail 12.1.5.70575 client")
    if hashlib.sha256(Path(info["path"]).read_bytes()).hexdigest() != CLIENT_SHA256:
        raise ValueError("selected client executable hash mismatch")


def safe_console_event(line: str):
    event = parse_console_line(line)
    if event:
        return event
    if any(value in line for value in ("Memory::ReadBytes", "ArgumentNullException",
                                       "Dont have a key", "Don't have a key")):
        return "capture_error", "CLIENT_INTEGRATION_FAILED"
    # All unrecognized text (including potentially personal/session data) is dropped.
    return None


def dump_statistics(path: Path) -> dict:
    parser = PktV31StreamParser()
    # Only names are shared. This does NOT grant 70575 payload/agent authority.
    manifest = OpcodeManifest.reviewed(70448)
    counts = {}
    total = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024*1024):
            for record in parser.feed(chunk):
                total += 1
                name = manifest.name(record.direction, record.opcode)
                if name:
                    counts[name] = counts.get(name, 0)+1
    return {"game_build": parser.header.game_build if parser.header else None,
            "records": total, "recognized_opcodes": counts,
            "incomplete_tail_bytes": parser.buffered_bytes,
            "semantic_live_validated": False}


def run(pid: int, seconds: int) -> dict:
    if not 10 <= seconds <= 180:
        raise ValueError("test duration must be between 10 and 180 seconds")
    if hashlib.sha256(CANDIDATE.read_bytes()).hexdigest() != CANDIDATE_SHA256:
        raise ValueError("test candidate hash mismatch")
    processes = process_list()
    if any(name.lower().startswith("ymir") for name, _ in processes):
        raise ValueError("Close the old Ymir / agent GUI first; another Ymir is running.")
    if [number for name, number in processes if name.lower() == "wow.exe"] != [pid]:
        raise ValueError("Keep only the explicitly selected WoW process open for this test.")
    check_client(pid)
    output = ROOT/"output/compat/ymir-70575"/datetime.now().strftime("test-%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True, exist_ok=False)
    report = {"selected_pid": pid, "candidate_sha256": CANDIDATE_SHA256,
              "client_file_verified": True, "detected_pid_verified": False,
              "expected_build": EXPECTED_BUILD, "allowed_build_verified": False,
              "full_ai_started": False, "successful_live_validation": False,
              "status": "RUNNING", "dump_path": None}
    process = subprocess.Popen([str(CANDIDATE)], cwd=str(output), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic()+seconds
    done = threading.Event()

    def timeout():
        while not done.wait(.2):
            if time.monotonic() >= deadline:
                if process.poll() is None:
                    process.terminate()
                return

    watchdog = threading.Thread(target=timeout, daemon=True)
    watchdog.start()
    print(f"YMIR test: PID {pid}, {seconds}s. Log in/reconnect manually now. Do NOT start FULL_AI.", flush=True)
    print("Private local test folder:", output, flush=True)
    try:
        for line in process.stdout:
            event = safe_console_event(line.strip())
            if event is None:
                continue
            kind, value = event
            if kind == "allowed_build":
                if value != EXPECTED_BUILD:
                    raise ValueError("candidate allowed-build mismatch")
                report["allowed_build_verified"] = True
                print("Allowed build:", value, flush=True)
            elif kind == "selected_pid":
                if value != pid:
                    raise ValueError("candidate selected a different PID; stopping")
                report["detected_pid_verified"] = True
                print("Selected PID verified:", value, flush=True)
            elif kind == "dump_path":
                path = (output/value).resolve()
                if not path.is_relative_to(output):
                    raise ValueError("capture path is outside this isolated test directory")
                report["dump_path"] = str(path)
                print("PKT recording started.", flush=True)
            elif kind == "capture_error":
                raise ValueError(value)
        report["exit_code"] = process.wait(timeout=5)
        report["status"] = "CAPTURE_ENDED_REQUIRES_REVIEW"
    except KeyboardInterrupt:
        report["status"] = "USER_STOPPED_REQUIRES_REVIEW"
    except Exception as error:
        report.update(status="ERROR", error=str(error))
    finally:
        done.set()
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        watchdog.join(timeout=1)
        process.stdout.close()
        path = Path(report["dump_path"]) if report.get("dump_path") else None
        if path and path.is_file():
            try:
                report["pkt"] = dump_statistics(path)
            except Exception as error:
                report["pkt_error"] = type(error).__name__
        (output/"status.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    if os.name != "nt":
        raise ValueError("Windows capture test only")
    pid = args.pid
    if pid is None:
        clients = [(name, number) for name, number in process_list() if name.lower() == "wow.exe"]
        if not clients:
            raise ValueError("Start WoW to the login screen first, then run this test.")
        print("WoW processes:", clients)
        default = str(clients[0][1]) if len(clients) == 1 else ""
        selected = input(f"Select WoW PID{f' [Enter = {default}]' if default else ''}: ").strip()
        pid = int(selected or default)
    report = run(pid, args.seconds)
    return 1 if report["status"] == "ERROR" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Test not started/stopped: {error}")
        raise SystemExit(1)
