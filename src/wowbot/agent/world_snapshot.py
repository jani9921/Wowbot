"""Read-only snapshot builders for :mod:`wowbot.agent.world`.

The WorldModel is the sole mutable reducer.  This module deliberately accepts
that model as a read source and returns immutable/planner or bounded/debug
projections; it never ingests observations, mutates beliefs, or selects work.
Type constructors are passed in by ``world.py`` to avoid a circular import.
"""
from __future__ import annotations

from heapq import nlargest
from itertools import islice
import math
from types import MappingProxyType

from .models import json_copy as deepcopy
from .world_state_contract import freeze


class WorldSnapshotProjection:
    """Physical home for planner and diagnostic read projections."""

    @staticmethod
    def planning(model, now: float, *, snapshot_type, fact_type,
                 sensor_health_type, reliability: dict):
        """Build one immutable planner view from the current reducer state."""
        state = MappingProxyType(dict(model.state))

        def observation_for(*sources):
            return next((model.source_latest[source] for source in sources
                         if source in model.source_latest), model.latest)

        def fact(value, *sources, confidence=None):
            obs = observation_for(*sources)
            source = obs.source if obs else (sources[0] if sources else "UNKNOWN")
            return fact_type(
                value=value,
                observed_at_monotonic=obs.received_at if obs else 0.,
                source_timestamp_wallclock=obs.timestamp if obs else None,
                observation_id=obs.observation_id if obs else "",
                source=source,
                confidence=(reliability.get(source, 0.) if confidence is None else confidence),
                revision=model.source_revisions.get(source, 0),
            )

        sensor_health = {}
        for source, revision in model.source_revisions.items():
            obs = model.source_latest.get(source)
            age = now-obs.received_at if obs else math.inf
            health = (sensor_health_type.HEALTHY if 0 <= age <= 2.
                      else sensor_health_type.DEGRADED if age <= 6.
                      else sensor_health_type.STALE if math.isfinite(age)
                      else sensor_health_type.FAILED)
            sensor_health[source] = {"status": health.value, "age": max(0., age),
                                     "revision": revision,
                                     "observation_id": obs.observation_id if obs else ""}
        ui = {key: state.get(key) for key in (
            "quest_ui", "extra_action", "gossip_ui", "vendor_ui", "bags_open", "world_map_open",
            "input_blocked", "loading")}
        combat = {key: state.get(key) for key in (
            "is_in_combat", "is_dead", "is_ghost", "is_casting", "target",
            "combat_last_spell_id", "combat_last_cast_at")}
        tracks = tuple(state.get("visual_candidates") or ())
        transaction = model.runtime_context.get("active_transaction")
        commitment = model.runtime_context.get("commitment")
        return snapshot_type(
            revision=model.revision, created_at_monotonic=now, session_id=model.session_id,
            player=fact(model.query.player(), "PLAYER_STATE", "ADDON_TELEMETRY"),
            target=fact(state.get("target"), "ADDON_TELEMETRY"),
            quests=fact(tuple(state.get("active_quests") or ()), "QUEST_STATE", "ADDON_TELEMETRY"),
            ui=fact(ui, "UI_CV", "ADDON_TELEMETRY"),
            combat=fact(combat, "ADDON_TELEMETRY"),
            world3d_tracks=fact(tracks, "WORLD3D"),
            entities=fact(tuple(model.entities.values()), "ADDON_TELEMETRY"),
            traversability=fact(state.get("local_traversability") or {}, "WORLD3D_LOCAL_VIEW", "WORLD3D"),
            movement=fact(state.get("movement") or {}, "PLAYER_STATE", "ADDON_TELEMETRY"),
            sensor_health=MappingProxyType(sensor_health),
            active_transaction=deepcopy(transaction) if transaction else None,
            active_commitment=deepcopy(commitment) if commitment else None,
            source_revisions=MappingProxyType(dict(model.source_revisions)),
            section_updates=MappingProxyType({
                key: MappingProxyType(dict(value))
                for key, value in model.section_updates.items()}),
            normalized_state=freeze(model._state_contract.build(model, now)),
            state=state, latest=model.latest, quest_model=model.quest_model,
            query=model.query, runtime_context=MappingProxyType(dict(model.runtime_context)),
            _model=model,
        )

    @staticmethod
    def diagnostic(model, now: float, *, addon_receive_fresh_seconds: float,
                   addon_detail_state_max_age_seconds: float) -> dict:
        """Build bounded status data without changing the authoritative store."""
        recent_relations = list(islice(reversed(model.relations.values()), 200))[::-1]
        recent_predictions = list(islice(reversed(model.predictions), 100))[::-1]
        recent_errors = list(islice(reversed(model.prediction_errors), 50))[::-1]
        recent_verifications = list(islice(reversed(model.verifications), 100))[::-1]
        recent_contradictions = list(islice(reversed(model.contradiction_history), 50))[::-1]
        # The evidence dict gains one key per distinct visual track ever seen
        # and is only pruned by the 60s maintenance pass, so it grows for the
        # life of a session. Every other field here is islice-bounded; this
        # one used to call the sort+JSON-heavy model.belief() on every live
        # key on every status build, a cost that grew linearly with session
        # length. Bound it to the 200 most recently *updated* keys. Plain
        # islice(reversed(...)) would be wrong: add_evidence() uses
        # setdefault, so long-lived, constantly refreshed keys (position,
        # target, mouseover) keep their early insertion slot and would be the
        # first ones dropped behind hundreds of newer track keys.
        def newest_active_at(entries):
            newest = None
            for item in entries:
                if item.expires >= now and (newest is None or item.at > newest):
                    newest = item.at
            return newest
        live_keys = ((newest, key) for key, entries in model.evidence.items()
                     if (newest := newest_active_at(entries)) is not None)
        belief_keys = [key for _, key in nlargest(200, live_keys)]
        return {
            "session_id": model.session_id, "fresh": model.fresh(now),
            "sensor_age": now-model.last_received,
            "freshness_policy": {
                "receive_gap_seconds": addon_receive_fresh_seconds,
                "paged_detail_state_is_liveness_gate": False,
                "paged_detail_max_age_seconds": addon_detail_state_max_age_seconds,
            },
            "player": model.state, "quests": model.objective_graph(),
            "entities": list(islice(reversed(model.entities.values()), 200))[::-1],
            "quest_records": model.quest_model.snapshot(), "quest_graph": model.quest_model.graph(),
            "entity_locations": dict(islice(reversed(model.entity_locations.items()), 200)),
            "entity_roles": dict(islice(reversed(model.entity_roles.items()), 200)),
            "entity_location_clusters": {
                identity: [vars(cluster) for cluster in clusters.values()]
                for identity, clusters in islice(reversed(model.entity_location_clusters.items()), 200)
            },
            "entity_states": dict(islice(reversed(model.entity_states.items()), 200)),
            "entity_appearances": dict(islice(reversed(model.entity_appearances.items()), 200)),
            "beliefs": {key: model.belief(key, now) for key in belief_keys},
            "events": list(model.events)[-20:],
            "predictions": [vars(item) for item in recent_predictions],
            "event_records": [vars(item) for item in list(model.event_records)[-50:]],
            "prediction_errors": [vars(item) for item in recent_errors],
            "verifications": [vars(item) for item in recent_verifications],
            "contradiction_history": [{
                "key": item.key, "status": item.status, "resolution": item.resolution,
                "chosen_value_sha256": __import__("hashlib").sha256(
                    item.chosen_value_json.encode()).hexdigest(),
                "chosen_value_bytes": len(item.chosen_value_json.encode("utf-8")),
                "supporting_observations": item.supporting_observations,
                "contradicting_observations": item.contradicting_observations, "at": item.at,
            } for item in recent_contradictions],
            "relations": [vars(item) for item in recent_relations],
            "diagnostic_totals": {
                "relations": len(model.relations), "predictions": len(model.predictions),
                "prediction_errors": len(model.prediction_errors),
                "verifications": len(model.verifications),
                "contradictions": len(model.contradiction_history),
            },
            "observation_sources": {source: sum(1 for item in model.history if item.source == source)
                                    for source in {item.source for item in model.history}},
            "section_updates": deepcopy(model.section_updates),
            "world_state_contract": model._state_contract.build(model, now),
        }
