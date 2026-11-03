"""Short, atomic resource leases; never a second input/skill authority.

Adapted from projekt_parallel's phase A. Compatible channels may overlap,
but one mouse, modal UI and the character's movement cannot have two owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import threading


class Resource(StrEnum):
    LEGS = "LEGS"
    BODY_YAW = "BODY_YAW"
    MOUSE = "MOUSE"
    ACTION_KEYS = "ACTION_KEYS"
    UI = "UI"


PRIORITY = {"SAFETY": 100, "UI": 90, "COMBAT": 80, "INTERACTION": 60,
            "LOCOMOTION": 40, "ATTENTION": 20}


@dataclass(frozen=True)
class Lease:
    owner: str
    priority: int
    expires_at: float


class ResourceArbiter:
    def __init__(self):
        self._leases = {}
        self._lock = threading.Lock()

    def request(self, owner, resources, priority, now, *, ttl=.15):
        wanted = {Resource(value) for value in resources}
        with self._lock:
            self._expire(now)
            if any(lease.owner != owner and lease.priority >= priority
                   for key, lease in self._leases.items() if key in wanted):
                return False
            for key in wanted:
                self._leases[key] = Lease(owner, priority, now+max(0., ttl))
            return True

    def _expire(self, now):
        self._leases = {key: lease for key, lease in self._leases.items() if lease.expires_at > now}

    def release(self, owner, resources=None):
        wanted = None if resources is None else {Resource(value) for value in resources}
        with self._lock:
            self._leases = {key: lease for key, lease in self._leases.items()
                            if lease.owner != owner or (wanted is not None and key not in wanted)}

    def revoke_all(self, now=None, reason=None):
        with self._lock:
            self._leases.clear()

    def snapshot(self, now):
        with self._lock:
            self._expire(now)
            return {key.value: {"owner": lease.owner, "priority": lease.priority,
                                "ttl": round(lease.expires_at-now, 3)}
                    for key, lease in self._leases.items()}
