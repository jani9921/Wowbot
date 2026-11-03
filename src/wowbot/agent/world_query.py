"""Read-only query boundary for the canonical WorldModel.

The query layer deliberately contains projections only.  It cannot ingest an
observation, mutate beliefs, select a skill, or dispatch input.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING

from wowbot.evidence_contracts import Evidence

from .entity_belief import EntityBelief, fuse_identity
from .evidence_freshness import FreshnessTier, classify
from .models import json_copy as deepcopy, number
from .next_quest_source_hierarchy import NextQuestSource, resolve_next_quest_source
from .supertrack_navigation_cue import NavigationCueSource, resolve_navigation_cue
from .soft_targeting import SoftTargetHint, SoftTargetMatch, observe_soft_targets, use_as_candidate_hint
from .ui_context import PrimaryPanel, UiContext, UiContextResolver
from .world_entities import EntityIdentity, LocationCluster, LocationObservation, RoleObservation

# V4-009: map each Evidence.source this model actually produces onto the
# spec's named lifetime categories. Approximate by source alone (the exact
# semantic category would also depend on the evidence *key*, which this
# read-only layer does not interpret) -- documented here rather than
# silently assumed.
_SOURCE_TO_FRESHNESS_CATEGORY = {
    "WORLD3D": "screen_space_bbox",
    "MINIMAP_CV": "minimap_marker",
    "WORLD_MAP_CV": "world_map_objective_area",
}

if TYPE_CHECKING:
    from .world import Prediction, WorldModel
    from .world_models import Belief, ContradictionRecord, WorldRelation


class WorldQuery:
    """Typed read-only facade; callers cannot mutate sensor projections."""

    def __init__(self, model: WorldModel, *, sensor_tiers: dict, source_tiers: dict):
        self.model = model
        self._sensor_tiers = sensor_tiers
        self._source_tiers = source_tiers
        self._ui_context_resolver = UiContextResolver()

    def player(self) -> dict:
        # DESIGN-013: `moving`/`vehicle`/`subzone` are real addon-reported
        # state; `control_mode` is deliberately NOT projected here -- that is
        # agent-level control authority (AutonomousAgent.mode), not perceived
        # world state, and folding it into this read-only projection would
        # blur the same WorldModel/agent boundary this codebase enforces
        # elsewhere (WorldModel never owns control authority).
        keys = ("map_id", "map_context", "position", "orientation", "health", "max_health", "power",
                "max_power", "is_mounted", "mount_capability", "is_in_combat", "is_dead",
                "is_ghost", "is_casting")
        result = {key: self.model.state.get(key) for key in keys}
        result["moving"] = bool(self.model.state.get("is_moving"))
        result["vehicle"] = bool(self.model.state.get("in_vehicle")
                                 or self.model.state.get("vehicle_ui")
                                 or self.model.state.get("vehicle_camera"))
        result["subzone"] = self.model.state.get("subzone_name")
        return deepcopy(result)

    def target(self) -> dict:
        return deepcopy(self.model.state.get("target") or {})

    def field_resolution(self, key: str, now: float):
        from wowbot.field_sources import FieldSourceResolver
        from .packet_continuity import eligible_evidence
        return FieldSourceResolver().resolve(key, eligible_evidence(self.model,self.model.evidence.get(key, ())), now,
                                             context={"session_id": self.model.session_id})

    def quest_pois(self, quest_id, now: float | None = None, *, objective_id=None, objective_index=None) -> tuple[dict, ...]:
        """The owned full packet geometry, copied only for the requested objective.

        A query does not turn polygons into targets or fill unknown heights.
        """
        from .world_packet_reducer import QUEST_POI_MAX_AGE, _context, _poi_scope
        from .packet_continuity import current
        if not current(self.model):
            return ()
        if now is None:
            now = max(self.model.last_received,
                      (self.model.__dict__.get('_packet_status') or {}).get('last_received_at', 0.))
        scope = self.model.__dict__.get('_packet_poi_context')
        if not scope or _poi_scope(_context(self.model, self.model.addon_state, scope['selected_pid'])) != scope:
            return ()
        record = (self.model.__dict__.get('_packet_quest_pois') or {}).get(str(quest_id)) or {}
        sampled = record.get('sampled_at')
        if (record.get('verified') is not True or type(sampled) not in {int, float}
                or not 0 <= now-sampled <= QUEST_POI_MAX_AGE):
            return ()
        return tuple(deepcopy({**blob, 'sample_time': sampled, 'source': 'PACKET_QUEST_POI'})
                     for blob in record.get('blobs') or ()
                     if (objective_id is None or str(blob.get('objective_id')) == str(objective_id))
                     and (objective_index is None or blob.get('objective_index') == objective_index))

    def quest_poi_status(self, quest_id, now: float | None = None) -> str:
        """Which gate of ``quest_pois`` holds the quest's server POI back (diagnostic only)."""
        from .world_packet_reducer import QUEST_POI_MAX_AGE, _context, _poi_scope
        from .packet_continuity import current
        if not current(self.model):
            return 'continuity_not_current'
        if now is None:
            now = max(self.model.last_received,
                      (self.model.__dict__.get('_packet_status') or {}).get('last_received_at', 0.))
        scope = self.model.__dict__.get('_packet_poi_context')
        if not scope:
            return 'no_poi_scope'
        if _poi_scope(_context(self.model, self.model.addon_state, scope['selected_pid'])) != scope:
            return 'poi_scope_mismatch'
        record = (self.model.__dict__.get('_packet_quest_pois') or {}).get(str(quest_id))
        if not record:
            return f"no_record:{len(self.model.__dict__.get('_packet_quest_pois') or {})}_quests"
        sampled = record.get('sampled_at')
        if record.get('verified') is not True or type(sampled) not in {int, float}:
            return 'unverified'
        if not 0 <= now-sampled <= QUEST_POI_MAX_AGE:
            return f'age:{round(now-sampled)}'
        return f"ok:{len(record.get('blobs') or ())}_blobs"

    def quest_objective_pois(self, quest_id, objective, now: float | None = None) -> tuple[dict, ...]:
        """Exact native objective identity precedes the legacy UI-row hint."""
        raw = getattr(objective, 'raw', None) or {}
        native = raw.get('server_objective_id')
        if native is not None:
            definition = self.quest_definition(quest_id, now)
            if (definition['status'] != 'OBSERVED_REFERENCE'
                    or definition['observation_id'] != raw.get('server_definition_evidence')):
                return ()
        key = str(objective.objective_id)
        exact = native or raw.get('quest_objective_id') or (key if key.isdigit() else None)
        if exact is not None:
            return self.quest_pois(quest_id, now, objective_id=exact)
        suffix = key.removeprefix(str(quest_id)+':')
        return (self.quest_pois(quest_id, now, objective_index=int(suffix))
                if key != suffix and suffix.isdigit() else ())

    def reference_entity(self, npc_id: int) -> dict | None:
        """Contextual memory/reference hint, never a current target identity."""
        knowledge = self.model.state.get("reference_knowledge") or {}
        return deepcopy((knowledge.get("entities") or {}).get(str(npc_id)))

    def quest_log_slots(self, now: float, *, quest_id=None) -> dict:
        """Own native slots; storage indices are not UI objective ordinals."""
        from .packet_quest_log import view
        from .world_packet_reducer import _context
        return view(self.model, self.model.state, now,
                    lambda pid: _context(self.model, self.model.state, pid), quest_id=quest_id)

    def quest_presence(self, quest_id: int, now: float) -> dict:
        if type(quest_id) is not int or not 0 < quest_id < 2**31:
            raise ValueError('positive quest ID required')
        result = self.quest_log_slots(now, quest_id=quest_id)
        present = any(row['fields'].get('quest_id', {}).get('value') == quest_id for row in result['slots'])
        state = ('PRESENT' if present else 'ABSENT' if result['membership'] == 'COMPLETE' else 'UNKNOWN')
        return {'state':state, 'source':'PACKET_QUEST_LOG', 'membership':result['membership'],
                'baseline_observed_at':result['baseline_observed_at']}

    def native_inventory(self, now: float, *, item_id=None) -> dict:
        """Owned native items, not client bag indices or an absence proof."""
        from .packet_inventory import view
        from .world_packet_reducer import _context
        return view(self.model,self.model.state,now,lambda pid:_context(self.model,self.model.state,pid),
                    item_id=item_id)

    def packet_stream_progress(self,now: float) -> dict:
        """Applied local control watermark; neither input nor world freshness."""
        from .runtime_packet_progress import view
        return view(self.model,now)

    def owned_item_count(self, item_id: int, now: float) -> dict:
        """A sampled lower bound of known owned stacks; carried state unknown."""
        if type(item_id) is not int or not 0 < item_id < 2**32:
            raise ValueError('positive item ID required')
        rows=self.native_inventory(now,item_id=item_id)['items']
        return {'item_id':item_id,'status':'OBSERVED_LOWER_BOUND' if rows else 'UNKNOWN',
                'count':sum(r['stack_count'] for r in rows) if rows else None,
                'carried':None,'complete':False,'source':'PACKET_OWN_INVENTORY',
                'evidence':[r['observation_id'] for r in rows],
                'sample_times':[r['sample_time'] for r in rows],
                'identity_evidence':[r['identity_evidence'] for r in rows],
                'identity_sample_times':[r['identity_sample_time'] for r in rows]}

    def quest_definition(self, quest_id, now: float | None = None) -> dict:
        """Observed, scoped quest structure; not an active/reward/actor fact."""
        from .server_quest_definitions import scope, view
        from .world_packet_reducer import _context
        owner = self.model.quest_model
        stored = owner.__dict__.get('_server_definition_scope')
        context = _context(self.model, self.model.state, stored['selected_pid']) if stored else None
        if self.model.state.get('loading') or self.model.state.get('player_present') is False:
            context = None
        provider = self.model.session_context_provider
        generation = provider.process.generation if provider is not None else None
        if now is None:
            now = max(self.model.last_received,
                      (self.model.__dict__.get('_packet_status') or {}).get('last_received_at', 0.))
        return view(owner, quest_id, scope(context, generation), now)

    def quest_objective_storage(self, quest_id, objective_id, now: float) -> dict:
        """Join an exact global objective ID to its reviewed storage field.

        A numeric storage sample does not assert objective/quest completion;
        bit objectives, conditional amounts and unsupported storage remain
        explicit unknowns rather than guessed UI-row counts.
        """
        unknown = {'status':'UNKNOWN', 'quest_id':quest_id, 'objective_id':objective_id}
        definition = self.quest_definition(quest_id, now)
        if definition['status'] != 'OBSERVED_REFERENCE':
            return unknown
        rows = definition['definition']['objectives']
        matches = [r for r in rows if str(r['objective_id']) == str(objective_id)]
        if len(matches) != 1:
            return unknown
        row = matches[0]
        storage = row['storage_index']
        if not 0 <= storage < 24 or sum(r['storage_index'] == storage for r in rows) != 1:
            return unknown
        slots = self.quest_log_slots(now, quest_id=quest_id)['slots']
        if len(slots) != 1 or str(storage) not in slots[0]['progress']:
            return unknown
        fact = slots[0]['progress'][str(storage)]
        return {**unknown, 'status':'OBSERVED_STORAGE', 'storage_index':storage,
                'value':fact['value'], 'sample_time':fact['observed_at'],
                'observation_id':fact['observation_id'], 'complete':None,
                'definition_evidence':definition['observation_id'],
                'definition_sample_time':definition['sample_time'],
                'required_amount':row['amount'], 'raw_type':row['raw_type']}

    def reference_quest(self, quest_id: int) -> dict | None:
        """Imported quest details; live progress remains in QuestModel."""
        knowledge = self.model.state.get("reference_knowledge") or {}
        return deepcopy((knowledge.get("quests") or {}).get(str(quest_id)))

    def soft_target_hints(self) -> tuple[SoftTargetHint, ...]:
        """Transient action-targeting evidence; never canonical identity."""
        return observe_soft_targets(self.model.state.get("soft_targets"))

    def soft_target_match(self, candidate: dict) -> SoftTargetMatch | None:
        """Score a pre-existing candidate against the current soft hints."""
        return use_as_candidate_hint(self.soft_target_hints(), candidate)

    def vendor(self) -> dict:
        """Fresh addon-ground-truth merchant window state."""
        return deepcopy(self.model.state.get("vendor_ui") or {})

    def ui_context(self) -> UiContext:
        """V4-011: one typed primary_panel/overlays/blocking_state snapshot.

        A caller should react to ``blocking_state`` first, per spec. Pure
        projection over already-stored state -- no new ingest, no mutation.
        """
        return self._ui_context_resolver.resolve(
            self.model.state, observed_at=float(self.model.last_received or 0.0))

    def ui_context_stable_for(self, milliseconds: float, *, now: float) -> bool:
        self.ui_context()
        return self._ui_context_resolver.stable_for(milliseconds, now=now)

    def invalidate_ui_context(self) -> None:
        self._ui_context_resolver.invalidate()

    def evidence_freshness(self, key: str, *, now: float) -> FreshnessTier | None:
        """V4-009: classify the freshest stored Evidence for ``key`` as FRESH/STALE/EXPIRED.

        Returns ``None`` when there is no evidence at all for ``key`` --
        that is "unknown", not "expired". The lifetime category is derived
        from the evidence's own ``source`` (see ``_SOURCE_TO_FRESHNESS_CATEGORY``);
        an unmapped source falls back to ``evidence_freshness.DEFAULT_POLICY``.
        """
        entries = self.model.evidence.get(key)
        if not entries:
            return None
        latest = max(entries, key=lambda item: item.at)
        category = _SOURCE_TO_FRESHNESS_CATEGORY.get(latest.source, latest.source)
        return classify(category, max(0.0, float(now) - float(latest.at)))

    def entity_belief(self, entity_id: str, *, now: float | None = None) -> EntityBelief:
        """V4-010: fuse this entity's recorded named-identity evidence.

        Ranked-source resolution per `fuse_identity()`; returns a zero-
        confidence `EntityBelief` when no identity evidence has been
        recorded for `entity_id` yet.
        """
        evidence = tuple(self.model.entity_identity_evidence.get(entity_id, ()))
        reference = self.model.last_received if now is None else now
        return fuse_identity(entity_id, evidence, now=reference)

    def navigation_cue(self) -> tuple[NavigationCueSource, object] | None:
        """V4-019: supertrack cue -> minimap -> world-map -> location belief.

        No supertrack-cue signal is exported by this build's addon/vision
        yet, so ``SUPERTRACK_CUE`` is always absent here -- documented
        rather than fabricated. The remaining three sources are real
        stored projections. Absence of a cue is not itself negative
        evidence about the quest; this only picks the next source.
        """
        available = {
            NavigationCueSource.SUPERTRACK_CUE: None,
            NavigationCueSource.MINIMAP_BELIEF: self.map_markers("MINIMAP") or None,
            NavigationCueSource.WORLD_MAP_BELIEF: self.map_markers("WORLD_MAP") or None,
            NavigationCueSource.LOCATION_BELIEF: self.get_best_search_region(),
        }
        return resolve_navigation_cue(available)

    def next_quest_source(self, *, same_npc_entity_id: str | None = None,
                          campaign_resolution: object | None = None
                          ) -> tuple[NextQuestSource, object] | None:
        """V4-063: after any turn-in, inspect resulting UI -> same NPC ->
        local markers -> tracker/log -> world map -> campaign
        classification, in that order. Never assumes the same NPC produced
        a new quest unless it genuinely still holds a QUEST_GIVER role.

        `same_npc_entity_id` / `campaign_resolution` are caller-supplied:
        "the NPC just turned in to" and "the campaign-continuation
        resolution" are attempt-scoped facts this read-only projection does
        not itself track, so those two sources are simply absent when
        omitted rather than guessed.
        """
        ui = self.ui_context()
        resulting_ui = ui if ui.primary_panel in {PrimaryPanel.GOSSIP, PrimaryPanel.QUEST_OFFER} else None

        same_npc = None
        if same_npc_entity_id is not None:
            giver_roles = [role for role in self.entity_roles(same_npc_entity_id) if role.role == "QUEST_GIVER"]
            same_npc = giver_roles[-1] if giver_roles else None

        local_markers = [item for item in self.visual_tracks()
                         if "quest_marker_like" in (item.get("candidate_labels") or ())]

        available = {
            NextQuestSource.RESULTING_UI: resulting_ui,
            NextQuestSource.SAME_NPC: same_npc,
            NextQuestSource.LOCAL_MARKERS: local_markers or None,
            NextQuestSource.TRACKER_LOG: self.get_current_quest_objectives() or None,
            NextQuestSource.WORLD_MAP: self.map_markers("WORLD_MAP") or None,
            NextQuestSource.CAMPAIGN_CLASSIFICATION: campaign_resolution,
        }
        return resolve_next_quest_source(available)

    def entity(self, entity_id: str) -> EntityIdentity | None:
        raw = self.model.entities.get(entity_id)
        if not raw:
            return None
        return EntityIdentity(entity_id, raw.get("npc_id"), tuple(raw.get("guids") or ()),
                              raw.get("name"), raw.get("unit_type"), raw["first_seen"], raw["last_seen"])

    def entity_locations(self, entity_id: str, *, map_id=None, phase=None, instance=None) -> list[LocationObservation]:
        result = []
        for raw in self.model.entity_locations.get(entity_id, []):
            if map_id is not None and raw.get("map_id") != map_id:
                continue
            if phase is not None and raw.get("phase") != phase:
                continue
            if instance is not None and raw.get("instance") != instance:
                continue
            result.append(LocationObservation(**deepcopy(raw)))
        return result

    def entity_location_clusters(self, entity_id: str) -> list[LocationCluster]:
        return [deepcopy(cluster) for cluster in self.model.entity_location_clusters.get(entity_id, {}).values()]

    def entity_roles(self, entity_id: str, *, quest_id=None, phase=None,
                     quest_revision=None) -> list[RoleObservation]:
        result = []
        for raw in self.model.entity_roles.get(entity_id, []):
            if quest_id is not None and str(raw.get("quest_id")) != str(quest_id):
                continue
            if phase is not None and raw.get("phase") != phase:
                continue
            if quest_revision is not None and str(raw.get("quest_revision")) != str(quest_revision):
                continue
            result.append(RoleObservation(**deepcopy(raw)))
        return result

    def map_markers(self, surface: str | None = None) -> list["MapMarker"]:
        # Legacy map-CV markers only; imported lazily so the SERVER path
        # loads no wowbot.vision module (REV4 2026-10-31).
        from wowbot.vision.models import MapMarker
        result = []
        for item in self.model.state.get("visual_candidates", []):
            if item.get("source") not in {"MINIMAP_CV", "WORLD_MAP_CV"}:
                continue
            marker = MapMarker.from_payload(item)
            if surface is None or marker.surface == surface:
                result.append(marker)
        return result

    def visual_tracks(self, source: str | None = None, kind: str | None = None,
                      minimum_confidence: float = 0.) -> list[dict]:
        result = []
        for item in self.model.state.get("visual_candidates", []):
            detector = item.get("detector_kind") or item.get("kind")
            if source and item.get("source") != source:
                continue
            if kind and detector != kind:
                continue
            if (number(item.get("confidence")) or 0) < minimum_confidence:
                continue
            result.append(deepcopy(item))
        return result

    def resources(self, resource_type: str | None = None, confirmed_only=True) -> list[dict]:
        result = []
        for item in self.model.state.get("resource_observations", []):
            kind = str(item.get("resource_type") or item.get("kind") or "").upper()
            if resource_type and kind != resource_type.upper():
                continue
            if confirmed_only and item.get("confirmed") is not True:
                continue
            result.append(deepcopy(item))
        return result

    def inventory(self) -> dict:
        return deepcopy(self.model.state.get("inventory") or {})

    def fishing(self) -> dict:
        return deepcopy(self.model.state.get("fishing") or {})

    def group(self) -> dict:
        return deepcopy(self.model.state.get("group_state") or {})

    def instance(self) -> dict:
        return deepcopy(self.model.state.get("instance_state") or {})

    def pvp(self) -> dict:
        return deepcopy(self.model.state.get("pvp_state") or {})

    def remembered_locations(self, semantic_types: set[str] | None = None) -> list[dict]:
        result = []
        for item in self.model.state.get("remembered_locations", []):
            if semantic_types and item.get("semantic_type") not in semantic_types:
                continue
            result.append(deepcopy(item))
        return result

    def recognition_candidates(self, track_id: str | None = None) -> list[dict]:
        return [deepcopy(item) for item in self.model.state.get("visual_recognition_candidates", [])
                if track_id is None or item.get("track_id") == track_id]

    def active_perception_ranking(self) -> list[dict]:
        return deepcopy(self.model.state.get("active_perception_ranking", []))

    def cross_view_hypotheses(self) -> list[dict]:
        return deepcopy(self.model.state.get("visual_cross_view_hypotheses") or [])

    def visual_track_belief(self, track_id: str, now: float | None = None) -> dict:
        return deepcopy(self.model.belief(f"visual_track:{track_id}",
                                          self.model.last_received if now is None else now))

    def local_world_view(self) -> dict:
        keys = ("world3d_batch", "local_traversability", "scene_geometry", "world3d_obstacles",
                "world3d_entrances", "world3d_landmarks", "world3d_interaction_candidates",
                "world3d_negative_evidence", "world3d_camera_state", "world3d_ego_motion")
        return deepcopy({key: self.model.state.get(key) for key in keys})

    def local_interactables(self) -> list[dict]:
        return deepcopy(self.model.state.get("world3d_interaction_candidates") or [])

    def local_entrances(self) -> list[dict]:
        return deepcopy(self.model.state.get("world3d_entrances") or [])

    def belief(self, key: str, now: float | None = None) -> dict:
        return deepcopy(self.model.belief(key, self.model.last_received if now is None else now))

    def typed_belief(self, key: str, now: float | None = None) -> Belief:
        return self.model.typed_belief(key, self.model.last_received if now is None else now)

    def evidence(self, key: str, now: float | None = None, *, include_inactive: bool = False) -> tuple[Evidence, ...]:
        """Immutable source records; values decode to isolated JSON copies."""
        current = self.model.last_received if now is None else now
        return tuple(entry for entry in self.model.evidence.get(key, ())
                     if include_inactive or entry.is_fresh(current))

    def contradiction_history(self, key: str | None = None) -> list[ContradictionRecord]:
        return [deepcopy(item) for item in self.model.contradiction_history
                if key is None or item.key == key]

    def sensor_hierarchy(self) -> dict[str, dict[str, object]]:
        return {source: {"tier": tier, "rank": self._sensor_tiers[tier]}
                for source, tier in self._source_tiers.items()}

    def relation(self, *, subject=None, predicate=None, object=None, minimum_confidence=0.) -> list[WorldRelation]:
        return [edge for edge in self.model.relations.values()
                if (subject is None or edge.subject == subject)
                and (predicate is None or edge.predicate == predicate)
                and (object is None or edge.object == object)
                and edge.confidence >= minimum_confidence]

    def predictions(self, *, kind: str | None = None, status: str | None = None) -> list[Prediction]:
        return [deepcopy(item) for item in self.model.predictions
                if (kind is None or item.prediction_kind == kind)
                and (status is None or str(item.status) == status)]

    def get_current_goal(self) -> dict | None:
        return deepcopy(self.model.runtime_context.get("goal"))

    def get_active_subgoal(self) -> dict | None:
        return deepcopy(self.model.runtime_context.get("subgoal"))

    def get_committed_target(self) -> dict | None:
        commitment = self.model.runtime_context.get("commitment") or {}
        guid = commitment.get("target_guid")
        target = self.target()
        if guid and target.get("guid") == guid:
            return target
        for entity in self.model.entities.values():
            if guid and guid in entity.get("guids", ()):
                return deepcopy(entity)
        return None

    def find_entities(self, *, npc_id=None, name=None, unit_type=None) -> list[dict]:
        result = []
        for entity in self.model.entities.values():
            if npc_id is not None and str(entity.get("npc_id")) != str(npc_id):
                continue
            if name is not None and str(entity.get("name") or "").casefold() != str(name).casefold():
                continue
            if unit_type is not None and str(entity.get("unit_type") or "").upper() != str(unit_type).upper():
                continue
            result.append(deepcopy(entity))
        return result

    def find_recent_tracks(self, *, source=None, lifecycle=None,
                           inspectable=None, minimum_confidence=0.) -> list[dict]:
        values = self.visual_tracks(source=source, minimum_confidence=minimum_confidence)
        return [item for item in values
                if (lifecycle is None or item.get("track_state") == lifecycle)
                and (inspectable is None or bool(item.get("inspectable")) == bool(inspectable))]

    def get_entity_locations(self, entity_id: str, **context) -> list[LocationObservation]:
        return self.entity_locations(entity_id, **context)

    def get_current_quest_objectives(self) -> list[dict]:
        return [asdict(value) if is_dataclass(value) else deepcopy(value)
                for value in self.model.quest_model.ready()]

    def get_best_search_region(self, semantic_types: set[str] | None = None) -> dict | None:
        locations = self.remembered_locations(semantic_types)
        if not locations:
            return None
        return max(locations, key=lambda item: (number(item.get("confidence")) or 0,
                                                number(item.get("last_seen")) or 0))

    def get_sensor_health(self, source: str | None = None) -> list[dict]:
        values = deepcopy(self.model.runtime_context.get("sensor_health") or [])
        return [item for item in values if source is None or item.get("source") == source]

    def get_world_uncertainties(self) -> list[dict]:
        result = []
        for key in self.model.evidence:
            belief = self.model.belief(key, self.model.last_received)
            if belief.get("status") in {"UNKNOWN", "CANDIDATE", "AMBIGUOUS"}:
                result.append({"key": key, **deepcopy(belief)})
        return result

    def get_recent_failures(self) -> list[dict]:
        return [asdict(item) if is_dataclass(item) else deepcopy(item)
                for item in self.model.prediction_errors]
