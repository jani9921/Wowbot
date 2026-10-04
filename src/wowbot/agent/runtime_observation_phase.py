from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from .models import Observation, canonical
from .visual_recognition_stabilizer import (
    _manual_mouseover_learning_probe,
    _publishable_visual_matches,
)

VISUAL_RECOGNITION_CACHE_SECONDS = 1.0


@dataclass(frozen=True)
class RuntimeObservationBatch:
    """Authority-neutral result of one runtime observation build."""

    base: Observation | None
    supplemental: tuple[Observation, ...]


def build_runtime_observations(
    runtime: Any,
    payload: dict | None,
    current: float,
    visual_candidates: list[dict],
) -> RuntimeObservationBatch:
    """Project addon, memory and passive vision data into observations.

    The function may update sensor-side caches and learned evidence, but it
    cannot dispatch input, choose a proposal or finalize a skill.  The caller
    retains all runtime and action authority.
    """
    supplemental: list[Observation] = []
    base_observation: Observation | None = None

    if payload:
        fast_lane = payload.get("transport_kind") == "FAST"
        probe = (
            runtime.agent.pending.proposal.parameters
            if runtime.agent.pending and runtime.agent.pending.proposal.skill == "INSPECT"
            else None
        )
        # A manual hover is passive ground truth.  It teaches only the exact
        # cursor/candidate association and never creates a target or command.
        if probe is None:
            probe = _manual_mouseover_learning_probe(payload, visual_candidates)
        if fast_lane:
            if probe is not None:
                runtime.spatial.ingest(payload, current, probe=probe, learn_only=True)
            remembered_locations = []
        else:
            remembered_locations = runtime.spatial.ingest(payload, current, probe=probe)

        base_observation = Observation.create(payload, current)
        common = {
            "session_id": base_observation.session_id,
            "timestamp": payload.get("timestamp"),
            "frame_id": base_observation.correlation_id,
        }
        addon_provenance = {
            "producer": "AIPlayerControllerExport",
            "parent_observation_id": base_observation.observation_id,
            "independence_group": base_observation.observation_id,
        }
        semantic_context = {
            "session_id": base_observation.session_id,
            "map_id": payload.get("map_id"),
            "phase": payload.get("phase"),
            "instance_id": payload.get("instance_id"),
            "quest_state_revision": payload.get("quest_state_revision"),
        }
        semantic_memory = []
        if not fast_lane:
            for lane in ("target", "mouseover"):
                unit = payload.get(lane) or {}
                subject = (
                    f"npc:{unit['npc_id']}"
                    if unit.get("npc_id") is not None
                    else f"guid:{unit['guid']}" if unit.get("guid") else None
                )
                role = unit.get("quest_role")
                role_source = unit.get("quest_role_source")
                token = (subject, "QUEST_ROLE", str(role), canonical(semantic_context))
                if (
                    subject
                    and role
                    and role != "UNKNOWN"
                    and role_source
                    and current - runtime._semantic_seen.get(token, -100) >= 2
                ):
                    runtime.memory.record_semantic_fact(
                        subject,
                        "QUEST_ROLE",
                        role,
                        semantic_context,
                        str(role_source),
                        current,
                        {
                            "observation_id": base_observation.observation_id,
                            "lane": lane,
                        },
                    )
                    runtime._semantic_seen[token] = current
            semantic_memory = runtime.memory.semantic_facts(
                context=semantic_context, supported_only=True
            )

        player_keys = (
            "map_id", "position", "orientation", "health", "max_health",
            "power", "max_power", "level", "class", "race", "is_mounted",
            "is_in_combat", "is_dead", "is_ghost", "is_casting", "movement",
            "player_world_position",
        )
        supplemental.append(Observation.create({
            **common,
            **{key: payload.get(key) for key in player_keys if key in payload},
            "provenance": addon_provenance,
        }, current, "PLAYER_STATE"))
        supplemental.append(Observation.create({
            **common,
            "mouseover": payload.get("mouseover"),
            "provenance": addon_provenance,
        }, current, "MOUSEOVER"))

        from wowbot.vision.ui_parser import parse_ui_observations
        supplemental.append(Observation.create({
            **common,
            "ui_observations": parse_ui_observations(
                payload, frame_id=base_observation.correlation_id, observed_at=current
            ),
            "provenance": addon_provenance,
        }, current, "UI_STATE"))

        from wowbot.vision.world_map_state import world_map_state
        supplemental.append(Observation.create({
            **common,
            "world_map_state": world_map_state(
                payload,
                frame_id=base_observation.correlation_id,
                observed_at=current,
                zoom_revision=runtime.agent.planner.map_zoom_count,
            ),
            "provenance": addon_provenance,
        }, current, "WORLD_MAP_STATE"))

        if not fast_lane:
            supplemental.append(Observation.create({
                **common,
                **{
                    key: payload.get(key)
                    for key in ("active_quests", "quest_locations", "quest_state_revision")
                    if key in payload
                },
                "provenance": addon_provenance,
            }, current, "QUEST_STATE"))
            tooltip = (
                (payload.get("map_mouseover") or {}).get("tooltip")
                or (payload.get("mouseover") or {}).get("tooltip_text")
            )
            from wowbot.vision.tooltip import tooltip_observation
            tooltip_record = tooltip_observation(
                payload,
                frame_id=base_observation.correlation_id,
                observed_at=current,
                cursor=payload.get("cursor_position"),
                candidates=visual_candidates,
            )
            supplemental.append(Observation.create({
                **common,
                "tooltip": tooltip,
                "tooltip_observation": tooltip_record,
                "provenance": addon_provenance,
            }, current, "TOOLTIP"))
            supplemental.append(Observation.create({
                **common,
                "remembered_locations": remembered_locations,
                "spawn_reference_candidates": runtime.spatial.spawn_reference(payload)["candidates"],
                "quest_role_reference_candidates": runtime.spatial.quest_role_reference(payload)["candidates"],
                "map_marker_observations": runtime.spatial.marker_observations,
                "confidence": .7,
                "provenance": {
                    "producer": "SpatialMemory",
                    "frame_id": base_observation.correlation_id,
                },
            }, current, "SPATIAL_MEMORY"))
            supplemental.append(Observation.create({
                **common,
                "semantic_memory_facts": semantic_memory,
                "confidence": .7,
                "provenance": {
                    "producer": "AgentMemory",
                    "frame_id": base_observation.correlation_id,
                },
            }, current, "SEMANTIC_MEMORY"))

        if (
            runtime.perception
            and runtime.perception.projection_revision
            != runtime._last_published_vision_revision
        ):
            runtime._last_published_vision_revision = runtime.perception.projection_revision
            _append_visual_projection(
                runtime,
                supplemental,
                common,
                base_observation,
                visual_candidates,
                current,
            )

    elif _control_vision_due(runtime):
        revision = runtime.perception.projection_revision
        runtime._last_control_vision_revision = revision
        items = [
            item for item in visual_candidates
            if item.get("source") in {"WORLD3D", "UI_CV"}
        ]
        pending_skill = runtime.agent.pending.proposal.skill
        control_lane = (
            pending_skill
            if pending_skill in {"VISUAL_APPROACH", "SEEK_VISUAL_CUE"}
            else "REFERENCE_REACH_SEARCH"
        )
        supplemental.append(Observation.create({
            "session_id": runtime.agent.world.session_id,
            "timestamp": current,
            "frame_id": f"vision-control:{runtime.perception.epoch}:{revision}",
            "surface": "WORLD3D",
            "visual_candidates": items,
            "confidence": max(
                (float(item.get("confidence", 0)) for item in items), default=0.
            ),
            "provenance": {
                "producer": "PerceptionWorker",
                "control_lane": control_lane,
                "projection_at": runtime.perception.projection_at,
            },
        }, current, "WORLD3D"))

    return RuntimeObservationBatch(base_observation, tuple(supplemental))


def _append_visual_projection(
    runtime: Any,
    supplemental: list[Observation],
    common: dict,
    base_observation: Observation,
    visual_candidates: list[dict],
    current: float,
) -> None:
    recognition_candidates = []
    # Live 2026-09-30: recognize_visual opened a new SQLite connection and ran
    # up to three queries (two 256-row similarity scans) for every candidate on
    # every agent step, ~20 % of the agent thread.  A signature only changes on
    # detector/canonical refreshes and the entity memory learns slowly, so a
    # one-second cache keeps recognition current without per-step cost.
    cache = getattr(runtime, "_visual_recognition_cache", None)
    if cache is None:
        cache = runtime._visual_recognition_cache = {}
    for candidate in visual_candidates:
        signature = candidate.get("visual_signature")
        if not signature:
            continue
        key = (str(signature.get("signature_id")) if isinstance(signature, dict)
               and signature.get("signature_id") else repr(signature))
        cached = cache.get(key)
        # A track's crop signature changes almost every frame, so the
        # signature cache rarely hit and recognize_visual (two 256-row
        # similarity scans) dominated the agent thread (live 2026-10-03,
        # ~18 % of samples).  Recognise one track at most once per window.
        track_key = ("track", str(candidate.get("track_id")))
        track_cached = cache.get(track_key) if candidate.get("track_id") is not None else None
        if cached is not None and 0 <= current-cached[0] <= VISUAL_RECOGNITION_CACHE_SECONDS:
            recognized = cached[1]
        elif (track_cached is not None
              and 0 <= current-track_cached[0] <= VISUAL_RECOGNITION_CACHE_SECONDS):
            recognized = track_cached[1]
        else:
            recognized = runtime.spatial.entities.recognize_visual(
                signature, as_of=time.time(), max_age=30 * 86400)
            if len(cache) >= 256:
                cache.clear()
            cache[key] = (current, recognized)
            if candidate.get("track_id") is not None:
                cache[track_key] = (current, recognized)
        matches = runtime._visual_recognition_stabilizer.update(
            candidate.get("track_id"),
            _publishable_visual_matches(recognized),
            current,
        )
        if matches:
            recognition_candidates.append({
                "track_id": candidate.get("track_id"),
                "surface": candidate.get("source"),
                "appearance_signature_id": signature.get("signature_id"),
                "entity_candidates": matches,
                "semantic_type": "UNKNOWN",
            })

    for source in ("MINIMAP_CV", "WORLD_MAP_CV", "WORLD3D", "UI_CV"):
        items = [
            {
                **item,
                **({"map_zoom_revision": runtime.agent.planner.map_zoom_count}
                   if source == "WORLD_MAP_CV" else {}),
            }
            for item in visual_candidates if item.get("source") == source
        ]
        supplemental.append(Observation.create({
            **common,
            "surface": source,
            "visual_candidates": items,
            "confidence": max(
                (float(item.get("confidence", 0)) for item in items), default=0.
            ),
            "provenance": {
                "producer": "PerceptionWorker",
                "frame_id": base_observation.correlation_id,
            },
        }, current, source))

    world3d_batch = getattr(runtime.perception, "world3d_batch", None)
    if world3d_batch is not None:
        batch_payload = world3d_batch.to_payload()
        supplemental.append(Observation.create({
            **common,
            "world3d_batch": batch_payload,
            "local_traversability": batch_payload["traversability"],
            "scene_geometry": batch_payload["scene_geometry"],
            "world3d_obstacles": batch_payload["obstacles"],
            "world3d_entrances": batch_payload["entrances"],
            "world3d_landmarks": batch_payload["landmarks"],
            "world3d_interaction_candidates": batch_payload["interaction_candidates"],
            "world3d_negative_evidence": batch_payload["negative_evidence"],
            "world3d_camera_state": batch_payload["camera_state"],
            "world3d_ego_motion": batch_payload["ego_motion"],
            "confidence": float(batch_payload["traversability"].get("confidence", 0.)),
            "provenance": {
                "producer": "World3DPipeline",
                "frame_id": batch_payload["frame_id"],
            },
        }, current, "WORLD3D_LOCAL_VIEW"))

    supplemental.append(Observation.create({
        **common,
        "visual_recognition_candidates": recognition_candidates,
        "confidence": max((
            min(.9, .5 + .05 * match["seen_count"])
            for candidate in recognition_candidates
            for match in candidate["entity_candidates"]
        ), default=0.),
        "provenance": {
            "producer": "EntityMemory",
            "frame_id": base_observation.correlation_id,
        },
    }, current, "ENTITY_MEMORY"))
    recognition_by_track = {
        str(item.get("track_id")): [item]
        for item in recognition_candidates if item.get("track_id") is not None
    }
    attention_ranking = runtime.agent.planner.active_perception.rank_world3d(
        visual_candidates,
        runtime.agent.world,
        runtime.agent.goal,
        recognition_by_track=recognition_by_track,
    )
    supplemental.append(Observation.create({
        **common,
        "active_perception_ranking": attention_ranking,
        "confidence": max(
            (item["expected_information_gain"] for item in attention_ranking), default=0.
        ),
        "provenance": {
            "producer": "ActivePerception",
            "mode": "READ_ONLY",
            "frame_id": base_observation.correlation_id,
        },
    }, current, "ACTIVE_PERCEPTION"))
    cross_view = runtime.cross_view.associate(
        visual_candidates, recognition_candidates, current
    )
    supplemental.append(Observation.create({
        **common,
        "visual_cross_view_hypotheses": cross_view,
        "confidence": max((item["confidence"] for item in cross_view), default=0.),
        "provenance": {
            "producer": "CrossViewAssociator",
            "frame_id": base_observation.correlation_id,
        },
    }, current, "CROSS_VIEW"))
    detector_diag = (
        (runtime.perception.diagnostics.get("world3d_v3_v4") or {})
        if isinstance(runtime.perception.diagnostics, dict) else {}
    )
    tracker_diag = detector_diag.get("tracker") or {}
    camera_motion = (
        tracker_diag.get("camera_motion_px")
        or ((detector_diag.get("detector") or {}).get("camera_motion_px"))
        or {}
    )
    supplemental.append(Observation.create({
        **common,
        "camera_state": {
            **runtime.agent.camera.snapshot(),
            "status": "ESTIMATED",
            "camera_motion_px": camera_motion,
            "source": "WORLD3D_GLOBAL_MOTION",
        },
        "confidence": float(camera_motion.get("confidence") or 0.),
        "provenance": {
            "producer": "PerceptionWorker",
            "frame_id": base_observation.correlation_id,
        },
    }, current, "CAMERA_CONTROL"))


def _control_vision_due(runtime: Any) -> bool:
    pending = runtime.agent.pending
    if not runtime.perception or not pending or not runtime.agent.world.session_id:
        return False
    skill = pending.proposal.skill
    parameters = pending.proposal.parameters
    eligible = skill in {"VISUAL_APPROACH", "SEEK_VISUAL_CUE"} or (
        skill in {"REACH_LOCATION", "REACH_OBJECT"}
        and parameters.get("source") == "TDB_REFERENCE"
        and parameters.get("purpose") == "INSPECT_REFERENCE_LOCATION"
    )
    return (
        eligible
        and runtime.perception.projection_revision
        != runtime._last_control_vision_revision
    )

