from __future__ import annotations

import ipaddress
import threading
import time
from typing import Iterable

from .models import FlowDirection, PidTcpFlow, TcpSegment


def _address(value) -> tuple[str, int] | None:
    if not value:
        return None
    ip = getattr(value, "ip", None)
    port = getattr(value, "port", None)
    if ip is None and isinstance(value, tuple) and len(value) >= 2:
        ip, port = value[0], value[1]
    if ip is None or port is None:
        return None
    try:
        return str(ipaddress.ip_address(str(ip).split("%", 1)[0])), int(port)
    except (ValueError, TypeError):
        return None


class PidFlowResolver:
    """Resolve TCP 4-tuples owned by exactly one explicitly selected PID."""

    def __init__(self, pid: int, *, refresh_interval: float = 0.5, connection_provider=None):
        if int(pid) <= 0:
            raise ValueError("selected PID must be positive")
        self.pid = int(pid)
        self.refresh_interval = max(0.1, float(refresh_interval))
        self.connection_provider = connection_provider
        self._flows: dict[tuple[str, int, str, int], PidTcpFlow] = {}
        self._last_refresh = float("-inf")
        self._lock = threading.Lock()

    def _connections(self) -> Iterable:
        if self.connection_provider is not None:
            return self.connection_provider()
        import psutil
        try:
            return psutil.Process(self.pid).net_connections(kind="tcp")
        except (psutil.NoSuchProcess, psutil.AccessDenied) as error:
            raise RuntimeError(f"cannot inspect TCP endpoints for PID {self.pid}: {error}") from error

    def refresh(self, now: float | None = None) -> tuple[PidTcpFlow, ...]:
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if now - self._last_refresh < self.refresh_interval:
                return tuple(self._flows.values())
            found: dict[tuple[str, int, str, int], PidTcpFlow] = {}
            try:
                connections = tuple(self._connections())
            except Exception:
                self._flows.clear()  # never retain stale PID ownership after resolver failure
                raise
            for connection in connections:
                local = _address(getattr(connection, "laddr", None))
                remote = _address(getattr(connection, "raddr", None))
                if local is None or remote is None:
                    continue
                key = (local[0], local[1], remote[0], remote[1])
                old = self._flows.get(key)
                found[key] = old or PidTcpFlow(self.pid, *key, first_seen=time.time())
            self._flows = found
            self._last_refresh = now
            return tuple(found.values())

    def match(self, segment: TcpSegment, now: float | None = None) -> tuple[PidTcpFlow, FlowDirection] | None:
        flows = self.refresh(now)
        forward = (segment.source_ip, segment.source_port,
                   segment.destination_ip, segment.destination_port)
        reverse = (segment.destination_ip, segment.destination_port,
                   segment.source_ip, segment.source_port)
        for flow in flows:
            key = (flow.local_ip, flow.local_port, flow.remote_ip, flow.remote_port)
            if forward == key:
                return flow, FlowDirection.CLIENT_TO_SERVER
            if reverse == key:
                return flow, FlowDirection.SERVER_TO_CLIENT
        return None

    @property
    def flows(self) -> tuple[PidTcpFlow, ...]:
        with self._lock:
            return tuple(self._flows.values())
