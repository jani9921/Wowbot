"""Bounded reference + learned-memory reads. No action or truth promotion."""
from __future__ import annotations

from copy import deepcopy
from .reference_experience import context_for
from .models import canonical


def positive_id(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


class ReferenceKnowledge:
    def __init__(self, catalog, entities):
        self.catalog, self.entities = catalog, entities
        from .tdb_knowledge import TDBKnowledgeProvider
        self.tdb = TDBKnowledgeProvider(catalog)
        self.experience = None
        self._key, self._at, self._snapshot = None, float("-inf"), {}

    def entity(self, npc_id):
        npc_id = positive_id(npc_id)
        if npc_id is None:
            return None
        reference = self.catalog.npc(npc_id)
        key = f"npc:{npc_id}"
        profile = self.entities.get_profile(key)
        if reference is None and profile is None:
            return None
        # Do not run behavior's historical scan from the medium loop.
        return deepcopy({"identity_key": key, "npc_id": npc_id,
            "reference": reference,
            "learned": {"name": profile.name if profile else None,
                        "seen_count": profile.seen_count if profile else 0,
                        "guids": self.entities.guids(key),
                        "locations": self.entities.locations(key, limit=8),
                        "visual_observations": self.entities.visual_observations(key, limit=4)},
            "current_identity_confirmed": False})

    def snapshot(self, state, now):
        """Two observed NPCs, up to 30 active and 10 live available quests.

        A context/identity change invalidates immediately. Learned coordinates
        stay separate from imported spawns; a player's position is not an NPC's.
        """
        npcs = tuple(dict.fromkeys(n for lane in ("target", "mouseover")
                     if (n := positive_id((state.get(lane) or {}).get("npc_id"))) is not None))
        active = tuple(dict.fromkeys(q for item in state.get("active_quests") or ()
                       if isinstance(item, dict) and (q := positive_id(item.get("quest_id"))) is not None))[:30]
        available = tuple(dict.fromkeys(q for item in (state.get('map_pois') or {}).get('available_quests') or ()
                       if isinstance(item, dict) and (q := positive_id(item.get('quest_id'))) is not None))[:10]
        quests = tuple(dict.fromkeys((*active, *available)))
        key = (canonical(context_for(state)), npcs, active, available,
               self.experience.revision if self.experience else 0)
        if key == self._key and 0 <= now-self._at < 1:
            return deepcopy(self._snapshot)
        entities = {}
        for npc_id in npcs:
            record = self.entity(npc_id)
            if record is None:
                continue
            if self.experience:
                record["learned"]["world_observations"] = self.experience.query(state, npc_id=npc_id, limit=8)
            reference = record["reference"]
            if reference:
                # Full raw SQL columns remain queryable on demand, not copied
                # into every runtime state or every status file.
                record["reference"] = {k: reference[k] for k in
                    ("npc_id", "name", "verified_build", "source", "confirmed", "source_file", "source_sha256", "quest_roles")
                    if k in reference}
            # Similarity still uses the original signature store. Projection
            # exposes bounded metadata rather than repeating large embeddings.
            for visual in record["learned"]["visual_observations"]:
                visual.pop("signature", None)
            entities[str(npc_id)] = record
            services = self.tdb.services(npc_id)
            record['services'] = {k:bool(services[k]) for k in ('gossip','vendor','trainers','spellclick')}
        quest_records = {}
        for quest_id in quests:
            record = self.tdb.quest(quest_id)
            learned = self.experience.query(state, quest_id=quest_id) if self.experience else []
            world = getattr(self.experience, "learned", None)
            learned_roles = world.quest_roles(quest_id) if world is not None else []
            if record or learned or learned_roles:
                projected = {k: deepcopy(record[k]) for k in
                    ("quest_id", "title", "objectives_text", "completion_text", "objectives",
                     "quest_roles", "object_roles", "chain", "eligibility", "items", "faction_variants",
                     "source", "verified_build", "confirmed", "source_file", "source_sha256") if record and k in record}
                projected.setdefault("quest_id", quest_id)
                # The TDB lacks some starters/enders (quest 55639): a role
                # verified live joins them, an identical TDB row is kept.
                known = {(r.get("npc_id"), r.get("role")) for r in projected.get("quest_roles") or ()}
                projected["quest_roles"] = list(projected.get("quest_roles") or []) + [
                    r for r in learned_roles if (r["npc_id"], r["role"]) not in known]
                if not record:
                    details = next((row for row in learned if row.get("kind") == "QUEST_DETAILS"), {})
                    for k in ("title", "completion_text", "description", "objectives", "source"):
                        if k in details:
                            projected[k] = deepcopy(details[k])
                    projected["confirmed"] = False
                all_pois = (record or {}).get('pois') or []
                world_map = (state.get('player_world_position') or {}).get('instance_id')
                scoped_pois = [p for p in all_pois if p.get('world_map_id')==world_map
                              and p.get('ui_map_id')==state.get('map_id')]
                projected['pois'] = [{k:deepcopy(v) for k,v in p.items() if k!='metadata'}
                                     for p in scoped_pois[:32]]
                for p in projected['pois']:
                    if len(p.get('points') or [])>256:
                        p['points']=[]
                        p['projection_status']='GEOMETRY_OVER_BUDGET_QUERY_PROVIDER'
                projected['poi_catalogue_count']=(record or {}).get('poi_catalogue_count',len(all_pois))
                projected['poi_superseded_count']=(record or {}).get('poi_superseded_count',0)
                projected['poi_projection_omitted']=len(all_pois)-len(projected['pois'])
                for objective in projected.get('objectives') or ():
                    objective.pop('metadata',None)
                    if len(objective.get('item_sources') or [])>12:
                        objective['item_sources_omitted']=len(objective['item_sources'])-12
                        objective['item_sources']=objective['item_sources'][:12]
                projected['learned_areas'] = (world.quest_areas(quest_id, world_map)
                                              if world is not None else [])
                projected['spawn_candidates'] = self.tdb.quest_locations(
                    {**(record or {}), "quest_roles": projected["quest_roles"]}, state, world)
                projected['live_status'] = 'ACTIVE' if quest_id in active else 'AVAILABLE_API'
                projected["learned"] = [{k:v for k,v in row.items() if k not in {"points", "evidence"}}
                                        for row in learned]
                projected["turnin_candidates"], projected["turnin_status"] = self.turnins(
                    {**record, "quest_roles": projected["quest_roles"]} if record else projected, learned)
                quest_records[str(quest_id)] = projected
        self._key, self._at = key, now
        self._snapshot = {"status": self.catalog.status,
                          "context": {k: state.get(k) for k in ("session_id", "map_id", "phase", "instance_id")},
                          "entities": entities, "quests": quest_records,
                          "policy": "TDB_PRIMARY_LIVE_VERIFIED",
                          "knowledge_priority": "PRIMARY_STATIC"}
        return deepcopy(self._snapshot)

    def turnins(self, reference, learned):
        verified = [row for row in learned if row.get("kind") == "QUEST_ROLE"
                    and row.get("role") == "QUEST_ENDER" and row.get("confirmed_historical")]
        if verified:
            # Distinct valid enders can coexist; never replace a phase variant.
            by_npc = {row["npc_id"]: row for row in reversed(verified)}
            return list(by_npc.values()), "LEARNED"
        if not reference:
            return [], "UNKNOWN"
        from .quest_turn_in import turn_in_from_text
        text = turn_in_from_text({}, {"completion_text": reference.get("completion_text")})
        roles = []
        for row in reference.get("quest_roles") or ():
            if row.get("role") == "QUEST_ENDER":
                npc = self.catalog.npc(row["npc_id"])
                name = (npc or {}).get("name") or row.get("name")
                if name:
                    roles.append({"npc_id": row["npc_id"], "name": name,
                                  "source": row.get("source") or "TDB_REFERENCE", "confirmed": False})
        if text and roles and not any(row["name"].casefold() == text["name"].casefold() for row in roles):
            # Keep the disagreement visible but do not nominate either NPC.
            return [], "AMBIGUOUS_TEXT_ROLE_CONFLICT"
        if text:
            source = ("ADDON_QUEST_HISTORY_TEXT" if reference.get("source") == "ADDON_QUEST_HISTORY"
                      else "TDB_REFERENCE_TEXT")
            return [{"name": text["name"], "source": source, "confirmed": False}], "HYPOTHESIS"
        return roles, "HYPOTHESIS" if roles else "UNKNOWN"
