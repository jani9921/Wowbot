from __future__ import annotations

from dataclasses import asdict, dataclass
import time

from .decoder import StreamDecoder
from .flows import PidFlowResolver
from .forwarder import EventSink
from .models import RawPacket
from .network import PacketDecodeError, decode_tcp
from .reassembly import TcpStreamReassembler


@dataclass
class PipelineDiagnostics:
    raw_packets: int = 0
    tcp_segments: int = 0
    pid_segments: int = 0
    stream_chunks: int = 0
    decoded_events: int = 0
    forwarded_events: int = 0
    filtered_events: int = 0
    decode_errors: int = 0
    last_packet_at: float | None = None
    last_event_at: float | None = None
    last_error: str | None = None


class PacketPipeline:
    def __init__(self, resolver: PidFlowResolver, decoder: StreamDecoder, sink: EventSink):
        self.resolver = resolver
        self.decoder = decoder
        self.sink = sink
        self.reassembler = TcpStreamReassembler()
        self.diagnostics = PipelineDiagnostics()

    def handle(self, packet: RawPacket) -> int:
        diag = self.diagnostics
        diag.raw_packets += 1
        diag.last_packet_at = packet.captured_at
        try:
            segment = decode_tcp(packet)
        except PacketDecodeError as error:
            diag.decode_errors += 1
            diag.last_error = str(error)
            return 0
        if segment is None:
            return 0
        diag.tcp_segments += 1
        try:
            matched = self.resolver.match(segment)
        except Exception:
            diag.decode_errors += 1
            diag.last_error = "pid_flow_resolution_failed"
            return 0
        if matched is None:
            return 0
        diag.pid_segments += 1
        flow, direction = matched
        if segment.flags & 2:
            self.decoder.reset_flow(flow.flow_id)
        before_resets = self.reassembler.resets
        chunk = self.reassembler.feed(segment, flow, direction)
        if chunk is None:
            if segment.flags & 5 or self.reassembler.resets > before_resets:
                self.decoder.reset_flow(flow.flow_id)
            return 0
        diag.stream_chunks += 1
        count = 0
        try:
            events = tuple(self.decoder.feed(chunk))
        except (ValueError, TypeError, OverflowError):
            diag.decode_errors += 1
            diag.last_error = "stream_decode_failed"
            self.reassembler.reset_flow(flow.flow_id)
            return 0
        for event in events:
            diag.decoded_events += 1
            diag.last_event_at = event.timestamp
            if self.sink.emit(event):
                diag.forwarded_events += 1
                count += 1
            else:
                diag.filtered_events += 1
        if segment.flags & 5:
            self.decoder.reset_flow(flow.flow_id)
        return count

    def snapshot(self) -> dict:
        value = asdict(self.diagnostics)
        value.update(
            selected_pid=self.resolver.pid,
            active_flows=[asdict(flow) | {"flow_id": flow.flow_id} for flow in self.resolver.flows],
            captured_at=time.time(),
        )
        return value

    def close(self) -> None:
        self.sink.close()
