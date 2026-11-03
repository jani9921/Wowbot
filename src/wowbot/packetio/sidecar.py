"""Explicitly launched passive transport sidecar. Never starts a game sniffer."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import signal
import threading
import time

from .capture import NpcapCapture
from .decoder import JsonLineSemanticDecoder, OpaqueStreamDecoder
from .flows import PidFlowResolver
from .forwarder import CompositeSink, EventPolicy, JsonlEventRecorder, UdpJsonForwarder
from .pipeline import PacketPipeline
from .pkt import OpcodeManifest, PktEventDecoder, PktFileFollower
from .builds import VERIFIED_OPCODE_BUILDS


def build_parser():
    parser = argparse.ArgumentParser(description="Passive PID-scoped packet observation sidecar")
    parser.add_argument("--list-interfaces", action="store_true")
    parser.add_argument("--pid", type=int, help="Exact selected WoW PID")
    parser.add_argument("--interface", help="Explicit Npcap interface")
    parser.add_argument("--decoder", choices=("opaque", "sandbox-jsonl"), default="opaque")
    parser.add_argument("--endpoint", type=Path, help="Current runtime's packet_endpoint.json (contains local IPC capability)")
    parser.add_argument("--record-only", action="store_true", help="Offline analysis, never forward into the live agent")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--allow-unknown", action="store_true")
    parser.add_argument("--npcap-dll", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--pkt-file", type=Path, help="Read an existing user-provided PKT 3.1 file")
    parser.add_argument("--pkt-owner-pid", type=int, help="Explicit user confirmation that this live PKT belongs to --pid; PKT has no PID")
    parser.add_argument("--opcode-map", type=Path, help="Optional pinned WPP 12.1.0/12.1.5 Opcodes.cs matching the capture build")
    return parser


def _write_diagnostics(path, value):
    if path is not None:
        from adapters.atomic_file import write_json_replace
        write_json_replace(path, value)


def _run_pkt(args, sink, stop):
    follower = PktFileFollower(args.pkt_file)
    decoder = header_seen = None
    diagnostics_at = 0.
    for record in follower.records(stop):
        header = follower.parser.header
        if header is not header_seen:  # file truncation/rotation must reset the codec too
            header_seen = header
            manifest = (OpcodeManifest.from_wpp_csharp(args.opcode_map, game_build=header.game_build)
                        if args.opcode_map else OpcodeManifest.reviewed(header.game_build)
                        if header.game_build in VERIFIED_OPCODE_BUILDS else None)
            decoder = PktEventDecoder(selected_pid=args.pid, header=header, manifest=manifest)
        for event in decoder.decode_all(record):
            sink.emit(event)
        now = time.monotonic()
        if now >= diagnostics_at:
            _write_diagnostics(args.diagnostics, follower.snapshot())
            diagnostics_at = now+1.
    return 0


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_interfaces:
        for item in NpcapCapture.list_interfaces(args.npcap_dll):
            print(f"{item.name}\t{item.description}\tflags={item.flags}")
        return 0
    if not args.pid or args.pid <= 0:
        parser.error("--pid must be the positive selected PID")
    if bool(args.interface) == bool(args.pkt_file):
        parser.error("select exactly one of --interface and --pkt-file")
    if args.record_only:
        if args.endpoint or args.record is None:
            parser.error("--record-only requires --record and forbids --endpoint")
    elif args.endpoint is None:
        parser.error("--endpoint is required for authenticated live forwarding")
    if args.pkt_file and not args.record_only and args.pkt_owner_pid != args.pid:
        parser.error("PKT has no PID: explicitly verify its origin with --pkt-owner-pid matching --pid")
    sinks = []
    if not args.record_only:
        sinks.append(UdpJsonForwarder(policy=EventPolicy(allow_unknown=args.allow_unknown),
                                      descriptor_path=args.endpoint))
    if args.record:
        sinks.append(JsonlEventRecorder(args.record, policy=EventPolicy(allow_unknown=True)))
    sink, stop = CompositeSink(*sinks), threading.Event()
    old_handlers = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        old_handlers[signum] = signal.signal(signum, lambda *_: stop.set())
    capture = None
    try:
        if args.pkt_file:
            return _run_pkt(args, sink, stop)
        resolver = PidFlowResolver(args.pid)
        decoder = JsonLineSemanticDecoder() if args.decoder == "sandbox-jsonl" else OpaqueStreamDecoder()
        pipeline = PacketPipeline(resolver, decoder, sink)
        capture = NpcapCapture(args.interface, dll_path=args.npcap_dll)
        diagnostics_at = 0.
        for packet in capture.packets(stop):
            pipeline.handle(packet)
            now = time.monotonic()
            if now >= diagnostics_at:
                _write_diagnostics(args.diagnostics, pipeline.snapshot())
                diagnostics_at = now+1.
        return 0
    finally:
        if capture is not None:
            capture.close()
        sink.close()
        for signum, old in old_handlers.items():
            signal.signal(signum, old)
