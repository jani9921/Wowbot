"""Bounded producer-owned quest geometry for a receiver that starts after login."""
from dataclasses import replace

from .models import AgentPacketEvent
from .validation import normalize_event, verified_semantics


class QuestPoiSnapshot:
    LIMIT = 64
    MAX_AGE = 1800.

    def __init__(self):
        self.events = {}

    def note(self, event):
        if event.event_type == 'MAP_CHANGED' and event.semantic_status == 'CONFIRMED':
            self.events.clear()
        if event.event_type != 'QUEST_POI_UPDATE':
            return
        try:
            safe = normalize_event(event.to_dict())
        except (ValueError, TypeError, OverflowError):
            return
        if not verified_semantics(safe):
            return
        qid = safe['payload']['quest_id']
        self.events.pop(qid, None)
        self.events[qid] = replace(event, payload=safe['payload'], provenance=safe['provenance'])
        while len(self.events) > self.LIMIT:
            self.events.pop(next(iter(self.events)))

    def replay(self, quest_id, now):
        event = self.events.get(quest_id)
        if event is None:
            return None
        captured = event.payload.get('capture_timestamp', event.timestamp)
        if not 0 <= now-captured <= self.MAX_AGE:
            self.events.pop(quest_id, None)
            return None
        # Transport freshness and source freshness are different. The reducer
        # converts this original capture time back to a monotonic sample age.
        return AgentPacketEvent.create(pid=event.selected_pid, flow_id=event.flow_id,
            direction=event.direction, event_type=event.event_type, timestamp=now,
            semantic_status=event.semantic_status, opcode=event.opcode,
            payload={**event.payload, 'capture_timestamp': captured},
            provenance=event.provenance, confidence=event.confidence)
