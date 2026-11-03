"""Observation -> shared evidence value; no fusion, input or provider ownership."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from wowbot.evidence_contracts import (
    Evidence, EvidenceCompleteness, EvidenceDirection, SourceLineage, finite_time,
)
from .models import canonical


def _text(value):
    return value if type(value) is str and value.strip() and len(value) <= 256 else None


def _ids(value):
    if value is None:
        return (), False
    if not isinstance(value, (list, tuple)):
        return (), True
    valid = tuple(dict.fromkeys(v for v in value[:64] if _text(v)))
    return valid, len(value) > 64 or any(_text(v) is None for v in value[:64])


def evidence_from_observation(key, value, obs, confidence, reliability, tier, rank, group, *, ttl, previous=(), observed_at=None):
    payload = obs.payload
    raw = payload.get("provenance")
    provenance = raw if isinstance(raw, Mapping) else {}
    invalid_group = (_text(group) is None or "independence_group" in provenance
                     and _text(provenance["independence_group"]) is None)
    group = _text(group) or obs.observation_id
    parents, bad_parents = _ids(provenance.get("parent_observation_ids"))
    parent = _text(provenance.get("parent_observation_id"))
    if parent is not None:
        parents = tuple(dict.fromkeys((*parents, parent)))
    if len(parents) > 64:
        parents, bad_parents = parents[:64], True
    roots, bad_roots = _ids(provenance.get("root_observation_ids"))
    known = {entry.observation_id: entry for entry in previous}
    if not roots and "root_observation_ids" not in provenance:
        if parents and all(p in known and known[p].lineage is not None for p in parents):
            roots = tuple(dict.fromkeys(root for p in parents for root in known[p].lineage.root_observation_ids))
            if len(roots) > 64:
                roots, bad_roots = roots[:64], True
        elif not parents:
            roots = (obs.observation_id,)
    event = payload.get("packet_event") if obs.source == "PACKET_TELEMETRY" else None
    event = event if isinstance(event, Mapping) else {}
    packet_provenance = event.get("provenance") or {}
    packet_provenance = packet_provenance if isinstance(packet_provenance, Mapping) else {}
    direction = event.get("direction", provenance.get("direction"))
    try:
        direction = EvidenceDirection(direction)
    except (ValueError, TypeError):
        direction = EvidenceDirection.UNKNOWN
    build = packet_provenance.get("game_build", payload.get("game_build"))
    if type(build) is str and build.isascii() and build.isdigit():
        build = int(build)
    build = build if type(build) is int and build > 0 else None
    lineage = SourceLineage(
        producer=_text(provenance.get("producer")), parent_observation_ids=parents,
        root_observation_ids=roots, event_id=_text(event.get("event_id") or provenance.get("source_event_id")),
        direction=direction, game_build=build,
        payload_layout=_text(packet_provenance.get("payload_layout") or provenance.get("payload_layout")),
        source_timestamp=obs.timestamp if finite_time(obs.timestamp) else None,
        correlation_uncertain=bad_parents or bad_roots or (raw is not None and not isinstance(raw, Mapping))
            or invalid_group
            or ("parent_observation_id" in provenance and parent is None)
            or ("root_observation_ids" in provenance and not roots and not parents))
    sampled, invalid = obs.received_at, None
    if "sampled_at_monotonic" in event:
        sampled = event["sampled_at_monotonic"]
    elif "observed_at_monotonic" in provenance:
        sampled = provenance["observed_at_monotonic"]
    elif parents and all(p in known for p in parents):
        sampled = min(known[p].observed_at for p in parents)
    if not finite_time(sampled):
        sampled, invalid = obs.received_at, "INVALID_OBSERVED_TIME"
    elif finite_time(obs.received_at) and sampled > obs.received_at:
        invalid = "INVALID_OBSERVED_TIME"
    if observed_at is not None:
        if not finite_time(observed_at) or observed_at > obs.received_at:
            invalid = "INVALID_OBSERVED_TIME"
        elif finite_time(sampled):
            sampled = min(sampled, observed_at)  # field age cannot rejuvenate a known origin
    ancestors = [known[identity] for identity in (*parents, *roots) if identity in known]
    if not lineage.correlation_uncertain and any(
            entry.lineage and entry.lineage.correlation_uncertain for entry in ancestors):
        lineage = replace(lineage, correlation_uncertain=True)
    if ancestors and finite_time(sampled):
        observed = [entry.observed_at for entry in ancestors if finite_time(entry.observed_at)]
        if observed:
            sampled = min(sampled, *observed)  # copying a known origin cannot rejuvenate it
        if any(entry.invalid_reason for entry in ancestors):
            invalid = "INVALID_ANCESTOR"
    if not finite_time(ttl) or ttl < 0:
        ttl, invalid = 0., "INVALID_LIFETIME"
    context = {"session_id": obs.session_id, "map_id": payload.get("map_id"), "surface": payload.get("surface")}
    packet_context = payload.get("packet_context") if event else None
    if isinstance(packet_context, Mapping):
        context.update({name: packet_context[name] for name in (
            "selected_pid", "character_guid", "map_id", "instance_id", "phase", "game_build",
            "runtime_id", "context_id") if name in packet_context})
    else:
        context.update({name: payload[name] for name in ("character_guid", "game_build", "phase") if name in payload})
        position = payload.get("player_world_position")
        if isinstance(position, Mapping) and "instance_id" in position:
            context["instance_id"] = position["instance_id"]
    try:
        collections = payload.get('collection_coverage')
        declared = (collections.get(key) if isinstance(collections, Mapping) and key in collections
                    else provenance.get('completeness', 'UNKNOWN'))
        if key in {'active_quests', 'inventory'} and (payload.get('loading') or payload.get('player_present') is False):
            declared = 'UNKNOWN'
        completeness = EvidenceCompleteness(declared)
    except (ValueError, TypeError):
        completeness = EvidenceCompleteness.UNKNOWN
    return Evidence(obs.observation_id, obs.correlation_id, obs.source, obs.received_at,
        sampled+ttl, canonical(value), confidence, reliability, canonical(context), group, tier, rank, key,
        str(payload.get("entity_id") or payload.get("guid") or "") or None,
        str(payload.get("quest_id") or "") or None, str(payload.get("objective_id") or "") or None,
        sampled_at_monotonic=sampled, lineage=lineage, completeness=completeness, invalid_reason=invalid)
