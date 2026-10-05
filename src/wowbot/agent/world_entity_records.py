"""WorldModel entity identity / location / role / state records.

Split out of world.py (2026-10-05, module-size gate); unchanged.
"""
from __future__ import annotations
import math
from .models import Observation, canonical, number
from .world_entities import AppearanceObservation, EntityStateObservation, LocationCluster, LocationObservation, RoleObservation
from .models import json_copy as deepcopy


class WorldEntityRecordsMixin:
    """Methods of WorldModel (world.py); moved verbatim."""

    def _record_entity_location(self, identity: str, position: dict, state: dict,
                                source: str, obs: Observation) -> LocationObservation | None:
        x, y, z = number(position.get("x")), number(position.get("y")), number(position.get("z"))
        if x is None or y is None:
            return None
        map_id = position.get("map_id", state.get("map_id"))
        phase, instance, zone = state.get("phase"), state.get("instance_id"), state.get("zone_name")
        coordinate_space = str(position.get("coordinate_space") or "NORMALIZED_MAP")
        context = canonical({"map_id": map_id, "phase": phase, "instance": instance,
                             "zone": zone, "coordinate_space": coordinate_space})
        clusters = self.entity_location_clusters.setdefault(identity, {})
        compatible = [cluster for cluster in clusters.values()
                      if cluster.context == context and math.hypot(x-cluster.center_x, y-cluster.center_y) <= .01]
        cluster = min(compatible, key=lambda item: math.hypot(x-item.center_x, y-item.center_y), default=None)
        if cluster is None:
            seed = canonical({"entity": identity, "context": context,
                              "cell_x": round(x/.005), "cell_y": round(y/.005)})
            cluster_id = __import__("hashlib").sha256(seed.encode()).hexdigest()[:24]
            cluster = LocationCluster(cluster_id, map_id, phase, instance, zone, context,
                                      coordinate_space, x, y, z, obs.received_at, obs.received_at,
                                      confidence=1., observation_ids=[obs.observation_id])
            clusters[cluster_id] = cluster
        else:
            count = cluster.seen_count + 1
            cluster.center_x = (cluster.center_x*cluster.seen_count+x)/count
            cluster.center_y = (cluster.center_y*cluster.seen_count+y)/count
            if z is not None:
                cluster.center_z = z if cluster.center_z is None else (cluster.center_z*cluster.seen_count+z)/count
            cluster.seen_count, cluster.last_seen = count, obs.received_at
            cluster.observation_ids = (cluster.observation_ids + [obs.observation_id])[-40:]
        record = LocationObservation(obs.observation_id, cluster.cluster_id, map_id, x, y, z,
                                     coordinate_space, phase, instance, zone, context, source, 1.,
                                     obs.received_at)
        locations = self.entity_locations.setdefault(identity, [])
        locations.append(vars(record))
        self.entity_locations[identity] = locations[-80:]
        return record

    def _record_entity_role(self, identity: str, unit: dict, state: dict,
                            source: str, obs: Observation) -> RoleObservation | None:
        role, role_source = unit.get("quest_role"), unit.get("quest_role_source")
        if not role or role == "UNKNOWN" or not role_source:
            return None
        quest_id, revision = unit.get("quest_id"), state.get("quest_state_revision")
        player_context = canonical({"level": state.get("level"), "combat": state.get("is_in_combat"),
                                    "quest_revision": revision, "session": obs.session_id})
        seed = canonical({"entity": identity, "role": role, "quest": quest_id,
                          "revision": revision, "phase": state.get("phase"),
                          "instance": state.get("instance_id"), "observation": obs.observation_id})
        role_id = __import__("hashlib").sha256(seed.encode()).hexdigest()[:24]
        record = RoleObservation(role_id, str(role), quest_id, revision, player_context,
                                 state.get("phase"), state.get("instance_id"), str(role_source),
                                 1., obs.received_at, obs.observation_id)
        roles = self.entity_roles.setdefault(identity, [])
        roles.append(vars(record))
        self.entity_roles[identity] = roles[-80:]
        return record

    def _record_entity_identity_evidence(self, identity: str, value, source_tag: str, obs: Observation) -> None:
        """V4-010: append one named-identity claim for later `fuse_identity()`."""
        if not value:
            return
        from .entity_belief import IdentityEvidence
        entries = self.entity_identity_evidence.setdefault(identity, [])
        entries.append(IdentityEvidence(str(source_tag), str(value), 1.0, obs.received_at))
        self.entity_identity_evidence[identity] = entries[-40:]

    def _record_entity_state_and_appearance(self, identity: str, unit: dict, state: dict,
                                            source: str, obs: Observation) -> None:
        values = {key: unit.get(key) for key in
                  ("health", "max_health", "dead", "is_dead", "attackable", "is_attackable",
                   "moving", "combat", "quest_available", "quest_complete") if key in unit}
        if values:
            seed = canonical({"entity": identity, "values": values, "observation": obs.observation_id})
            record = EntityStateObservation(__import__("hashlib").sha256(seed.encode()).hexdigest()[:24],
                values, state.get("phase"), state.get("instance_id"), source,
                obs.received_at, obs.observation_id)
            states = self.entity_states.setdefault(identity, [])
            states.append(vars(record)); self.entity_states[identity] = states[-80:]
        signature = unit.get("visual_signature") or unit.get("appearance")
        if isinstance(signature, dict) and signature:
            representation = str(signature.get("representation_space") or "UNKNOWN")
            seed = canonical({"entity": identity, "signature": signature,
                              "representation": representation, "observation": obs.observation_id})
            record = AppearanceObservation(__import__("hashlib").sha256(seed.encode()).hexdigest()[:24],
                representation, deepcopy(signature), source, obs.received_at, obs.observation_id)
            appearances = self.entity_appearances.setdefault(identity, [])
            appearances.append(vars(record)); self.entity_appearances[identity] = appearances[-80:]
