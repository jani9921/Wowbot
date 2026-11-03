from __future__ import annotations

import ipaddress
import struct

from .models import RawPacket, TcpSegment


DLT_NULL = 0
DLT_EN10MB = 1
DLT_RAW = 12
DLT_IPV4 = 228
DLT_IPV6 = 229


class PacketDecodeError(ValueError):
    pass


def _tcp(raw: RawPacket, packet: bytes, offset: int, source: str, destination: str) -> TcpSegment | None:
    if len(packet) < offset + 20:
        raise PacketDecodeError("truncated TCP header")
    source_port, destination_port, sequence, acknowledgement, data_offset_flags = struct.unpack_from(
        "!HHIIH", packet, offset
    )
    header_length = ((data_offset_flags >> 12) & 0xF) * 4
    if header_length < 20 or len(packet) < offset + header_length:
        raise PacketDecodeError("invalid TCP data offset")
    return TcpSegment(
        captured_at=raw.captured_at,
        source_ip=source,
        source_port=source_port,
        destination_ip=destination,
        destination_port=destination_port,
        sequence=sequence,
        acknowledgement=acknowledgement,
        flags=data_offset_flags & 0x1FF,
        payload=packet[offset + header_length :],
    )


def _ipv4(raw: RawPacket, packet: bytes, offset: int) -> TcpSegment | None:
    if len(packet) < offset + 20:
        raise PacketDecodeError("truncated IPv4 header")
    version_ihl = packet[offset]
    if version_ihl >> 4 != 4:
        raise PacketDecodeError("not IPv4")
    header_length = (version_ihl & 0xF) * 4
    total_length = struct.unpack_from("!H", packet, offset + 2)[0]
    fragment = struct.unpack_from("!H", packet, offset + 6)[0]
    if header_length < 20 or len(packet) < offset + header_length:
        raise PacketDecodeError("invalid IPv4 header length")
    if fragment & 0x3FFF:  # MF and fragment offset: never decode a partial IP datagram
        return None
    if packet[offset + 9] != 6:
        return None
    if total_length < header_length + 20 or len(packet) < offset+total_length:
        raise PacketDecodeError("invalid or truncated IPv4 datagram")
    end = offset + total_length
    source = str(ipaddress.ip_address(packet[offset + 12 : offset + 16]))
    destination = str(ipaddress.ip_address(packet[offset + 16 : offset + 20]))
    return _tcp(raw, packet[:end], offset + header_length, source, destination)


def _ipv6(raw: RawPacket, packet: bytes, offset: int) -> TcpSegment | None:
    if len(packet) < offset + 40:
        raise PacketDecodeError("truncated IPv6 header")
    if packet[offset] >> 4 != 6:
        raise PacketDecodeError("not IPv6")
    payload_length = struct.unpack_from("!H", packet, offset + 4)[0]
    if not payload_length or len(packet) < offset+40+payload_length:
        raise PacketDecodeError("invalid or truncated IPv6 datagram")
    packet = packet[:offset+40+payload_length]
    next_header = packet[offset + 6]
    cursor = offset + 40
    # Walk the common extension headers. Fragmented packets are intentionally
    # ignored; IP fragment reassembly belongs below the TCP stream layer.
    while next_header in {0, 43, 60, 44}:
        if next_header == 44:
            return None
        if len(packet) < cursor + 2:
            raise PacketDecodeError("truncated IPv6 extension header")
        following = packet[cursor]
        extension_length = (packet[cursor + 1] + 1) * 8
        cursor += extension_length
        next_header = following
    if next_header != 6:
        return None
    source = str(ipaddress.ip_address(packet[offset + 8 : offset + 24]))
    destination = str(ipaddress.ip_address(packet[offset + 24 : offset + 40]))
    return _tcp(raw, packet, cursor, source, destination)


def decode_tcp(raw: RawPacket) -> TcpSegment | None:
    packet = raw.payload
    if raw.link_type == DLT_EN10MB:
        if len(packet) < 14:
            raise PacketDecodeError("truncated Ethernet header")
        ether_type = struct.unpack_from("!H", packet, 12)[0]
        offset = 14
        while ether_type in {0x8100, 0x88A8}:
            if len(packet) < offset + 4:
                raise PacketDecodeError("truncated VLAN header")
            ether_type = struct.unpack_from("!H", packet, offset + 2)[0]
            offset += 4
        if ether_type == 0x0800:
            return _ipv4(raw, packet, offset)
        if ether_type == 0x86DD:
            return _ipv6(raw, packet, offset)
        return None
    if raw.link_type == DLT_NULL:
        if len(packet) < 4:
            raise PacketDecodeError("truncated loopback header")
        family = struct.unpack_from("<I", packet, 0)[0]
        if family == 2:
            return _ipv4(raw, packet, 4)
        if family in {23, 24, 28, 30}:
            return _ipv6(raw, packet, 4)
        return None
    if raw.link_type in {DLT_RAW, DLT_IPV4, DLT_IPV6}:
        version = packet[0] >> 4 if packet else 0
        return _ipv4(raw, packet, 0) if version == 4 else _ipv6(raw, packet, 0) if version == 6 else None
    raise PacketDecodeError(f"unsupported pcap link type {raw.link_type}")
