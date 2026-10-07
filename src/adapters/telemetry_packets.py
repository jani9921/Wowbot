"""Versioned AIPC5 page reassembly. Incomplete snapshots never become facts."""
from __future__ import annotations

import json
import base64
import math
import zlib
import time


ARRAYS = {"actionbar", "active_quests", "quest_locations", "killed_corpses", "events", "visible_units"}


def _num(value, default=0.0):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default


FAST_SAMPLE_TIME_KEYS = ("fast_sample_time", "target_sample_time",
                         "mouseover_sample_time", "cursor_sample_time")


def _stamp_world_position(value: dict) -> None:
    """Mark when this packet measured the player's world position.

    A FAST observation id is not a new position measurement: a packet without
    a position leaves the older one in the merged state.  ``sample_time`` lets
    consumers tell a fresh measurement from a carried-over one."""
    position = value.get("player_world_position")
    if isinstance(position, dict) and value.get("monotonic_time") is not None:
        position["sample_time"] = value.get("monotonic_time")


def _complete_fast_sample(value: dict) -> None:
    """Restore what bounded FAST variants (addon 0.9.38+) leave out."""
    sample_time = value.get("monotonic_time")
    if sample_time is not None:
        for key in FAST_SAMPLE_TIME_KEYS:
            value.setdefault(key, sample_time)
    position = value.get("player_world_position")
    if isinstance(position, dict):
        position.setdefault("source", "C_MAP_PLAYER_WORLD_POS")
        position.setdefault("ui_map_id", value.get("map_id"))
        position.setdefault("z_known", False)
        position.setdefault("z_source", "NAVMESH_XY_PROJECTION_REQUIRED")
    _stamp_world_position(value)


def normalize(value: dict) -> dict:
    # Addon 0.9.61 sent a secret UnitHealth("player") as 0 on every FAST
    # packet: a living player at 0 health is unknown health, never 0 %.
    if (value.get("health") == 0 and value.get("is_dead") is not True
            and value.get("is_ghost") is not True):
        value["health"] = None
    for key in ARRAYS:
        if value.get(key) == {}:
            value[key] = []
        if key in value and (not isinstance(value[key], list) or any(not isinstance(x, dict) for x in value[key])):
            raise ValueError(f"AIPC5 {key} must be an object array")
    for key in ("quest_ui", "extra_action", "inventory", "position", "target", "mouseover", "map_mouseover", "combat_hint", "map_context"):
        if value.get(key) and not isinstance(value[key], dict):
            raise ValueError(f"AIPC5 {key} must be an object")
    pois = value.get("map_pois")
    if pois is not None:
        # Optional map-API knowledge (addon 0.9.37): a malformed list drops
        # that list only, never the whole snapshot.
        if not isinstance(pois, dict):
            value["map_pois"] = pois = {}
        for key in ("available_quests", "dungeon_entrances", "taxi_nodes", "area_pois"):
            rows = pois.get(key)
            pois[key] = ([row for row in rows if isinstance(row, dict)]
                         if isinstance(rows, list) else [])
    for quest in value.get("active_quests", []):
        if quest.get("objectives") == {}:
            quest["objectives"] = []
    ui = value.get("quest_ui") or {}
    if ui.get("entries") == {}:
        ui["entries"] = []
    inv = value.get("inventory") or {}
    if inv.get("items") == {}:
        inv["items"] = []
    target = value.get("target") or {}
    # map_context is part of the compact FAST lane.  Treat its map-open bit
    # as the canonical current value and mirror it to the legacy top-level
    # field consumed by skills.  Without this projection CLOSE_MAP can close
    # the map successfully, miss verification for five seconds, then retry
    # the toggle and reopen it (live-observed 2026-09-27).
    map_context = value.get("map_context") or {}
    nested_map_open = map_context.get("world_map_open")
    if isinstance(nested_map_open, bool):
        value["world_map_open"] = nested_map_open
    player_world = value.get("player_world_position")
    # Addon 0.9.28 combined C_Map X/Y with Retail UnitPosition's numeric but
    # false player Z=0 and marked that height authoritative.  This source
    # combination is invalid by contract (0.9.29 never emits it).  Reject it
    # defensively at the transport boundary so an older installed addon
    # cannot select a lower stacked mmap layer.
    if (isinstance(player_world, dict)
            and player_world.get("source") == "C_MAP_PLAYER_WORLD_POS"
            and player_world.get("z_source") == "UNIT_POSITION"):
        player_world["z_known"] = False
        player_world["z_observed"] = False
        player_world["z_estimated"] = False
        player_world["z_source"] = "LEGACY_UNIT_POSITION_Z_REJECTED"
    value["current_target"] = target.get("name")
    value["target_is_attackable"] = target.get("attackable", target.get("is_attackable"))
    value["target_is_dead"] = target.get("dead", target.get("is_dead"))
    value["dead_corpses"] = value.get("killed_corpses", [])
    value["quest_ui_open"] = ui.get("open", False)
    for key in ("action", "x", "y", "quest_id"):
        value["quest_ui_" + key] = ui.get(key)
    value["quest_ui_entries"] = ui.get("entries", [])
    # PREPARED 2026-09-14, UNTESTED LIVE (needs the corresponding addon
    # change installed/reloaded too). Fast-lane mirror of quest_ui's own
    # flattening above, for the same reason: skills.py's COMBAT/DEFEND
    # verify() otherwise only sees a landed spell cast via the slow/paged
    # `events` list. See docs/LIVE_VALIDATION.md for the test checklist.
    combat_hint = value.get("combat_hint") or {}
    value["combat_last_spell_id"] = combat_hint.get("spell_id")
    value["combat_last_cast_at"] = combat_hint.get("at")
    value["protocol_version"] = "AIPC5"
    value["telemetry_source"] = "retail_pixel_bridge"
    digest = value.get("quest_digest")
    if digest == {}:
        digest = []
    if isinstance(digest, list):
        value["accepted_quest_ids"] = [item.get("id") for item in digest
                                         if isinstance(item, dict) and item.get("id")]
        if not value.get("active_quests") and digest:
            value["active_quests"] = [{
                "quest_id": item.get("id"), "is_accepted": True,
                "is_complete": bool(item.get("complete")),
                "source": "FAST_QUEST_DIGEST",
                "objectives": [{"current": _num(item.get("done")),
                                "required": _num(item.get("need"), 1.0) or 1.0,
                                "is_complete": bool(item.get("complete"))}],
            } for item in digest if isinstance(item, dict) and item.get("id")]
    return value


class PacketAssembler:
    def __init__(self):
        self.session = None
        self.groups = {}
        self.full = None
        self.last_full = -1
        self.last_fast = -1
        self.full_received_at = 0.
        self.last_fast_payload = {}
        # (epoch timestamp, addon monotonic_time) of the newest packet that
        # carried its own timestamp; restored values never become anchors.
        self.clock_anchor = None

    def _note_clock_anchor(self, value: dict) -> None:
        stamp, mono = _num(value.get("timestamp"), None), _num(value.get("monotonic_time"), None)
        if stamp is None or mono is None:
            return
        if self.clock_anchor is None or mono >= self.clock_anchor[1]:
            self.clock_anchor = (stamp, mono)

    def _restore_timestamp(self, value: dict) -> None:
        """Live 2026-10-06 09:42 (hunter pet tooltip): the bounded FAST
        variants carry no epoch ``timestamp``.  WorldModel read 0 < latest
        and dropped every packet as out-of-order for 25 s while the receive
        clock still looked fresh: the agent stood frozen.  Rebuild it from the
        last stamped sample and the addon's own monotonic clock, floored so
        it never runs ahead of the addon's integer-second ``time()``."""
        if value.get("timestamp") is not None:
            self._note_clock_anchor(value)
            return
        # Issue #80: anchoring on the previous (already restored, floored)
        # FAST froze the clock at one second forever and let an old FAST win
        # over a newer full snapshot. Only genuinely stamped packets anchor.
        if self.clock_anchor is None:
            return
        base, anchor_mono = self.clock_anchor
        mono = _num(value.get("monotonic_time"), None)
        elapsed = max(0., mono-anchor_mono) if mono is not None else 0.
        value["timestamp"] = math.floor(base + elapsed)

    def feed_lanes(self, packets: list[str], now: float | None = None) -> dict | None:
        """All packets of one two-lane frame: FAST first, so a snapshot the
        STATE lane completes in the same frame already merges it; the
        completed snapshot then wins as the frame's result.  One bad lane does
        not discard the other."""
        now = time.monotonic() if now is None else now
        ordered = sorted(packets, key=lambda packet: 0 if packet.split("|", 6)[5:6] == ["FAST"] else 1)
        result, errors = None, []
        for packet in ordered:
            try:
                value = self.feed(packet, now)
            except ValueError as error:
                errors.append(error)
                continue
            if value is not None and (result is None or value.get("transport_kind") != "FAST"):
                result = value
        if result is None and errors and len(errors) == len(ordered):
            raise errors[0]
        return result

    def feed(self, payload: str, now: float | None = None) -> dict | None:
        now = time.monotonic() if now is None else now
        if "\n" in payload:
            return self.feed_lanes([part for part in payload.split("\n") if part], now)
        parts = payload.split("|", 6)
        if len(parts) != 7 or parts[0] != "AIPC5":
            raise ValueError("invalid AIPC5 packet")
        _, session, seq_raw, index_raw, count_raw, kind, body = parts
        seq, index, count = int(seq_raw), int(index_raw), int(count_raw)
        # A single-strip body is at most ~950 bytes; a two-lane strip lane at
        # most 8*1024-8.  4096 bounds both (the capture buffer slot size).
        if kind not in {"FAST", "STATE", "STATE_Z"} or seq < 0 or not 1 <= count <= 160 or not 0 <= index < count or len(body.encode()) > 4096:
            raise ValueError("invalid AIPC5 bounds")
        if session != self.session:
            self.__init__()
            self.session = session
        if kind == "FAST":
            if seq <= self.last_fast or count != 1:
                return None
            value = json.loads(body)
            if not isinstance(value, dict):
                raise ValueError("AIPC5 FAST must be object")
            _complete_fast_sample(value)
            self._restore_timestamp(value)
            self.last_fast = seq
            self.last_fast_payload = value
            if self.full is None:
                return None
            # Publish a bounded delta, not a copy of the potentially 100+ KB
            # full snapshot at FAST_STATE frequency. WorldModel owns the
            # authoritative merge. Stable identity fields are included only
            # so the Observation/session safety boundary remains explicit.
            result = dict(value)
            for key in ("character_guid", "character_name", "addon",
                        "addon_version", "schema_version", "game_version"):
                if key in self.full:
                    result[key] = self.full[key]
        else:
            if seq <= self.last_full:
                return None
            self.groups = {k: g for k, g in self.groups.items() if now - g[0] < 30 and k >= seq - 2}
            created, expected, chunks, encoding = self.groups.setdefault(seq, (now, count, {}, kind))
            if expected != count or encoding != kind or index in chunks and chunks[index] != body:
                self.groups.pop(seq, None)
                raise ValueError("conflicting AIPC5 pages")
            chunks[index] = body
            if len(chunks) != count:
                return None
            encoded = "".join(chunks[i] for i in range(count))
            if kind == "STATE_Z":
                raw = base64.b64decode(encoded, validate=True)
                decompressor = zlib.decompressobj()
                decoded = decompressor.decompress(raw, 128001)
                if len(decoded) > 128000 or not decompressor.eof or decompressor.unused_data:
                    raise ValueError("invalid or oversized AIPC5 compressed state")
                encoded = decoded.decode("utf-8")
            value = json.loads(encoded)
            if not isinstance(value, dict):
                raise ValueError("AIPC5 STATE must be object")
            self.full = normalize(value)
            self._note_clock_anchor(self.full)
            _stamp_world_position(self.full)
            self.full["state_encoding"] = kind
            self.last_full = seq
            self.full_received_at = now
            self.groups.clear()
            fast = self.last_fast_payload
            # A newer full snapshot wins over an older FAST sample.
            if float(fast.get("monotonic_time") or 0) >= float(value.get("monotonic_time") or 0):
                result = {**self.full, **fast}
            else:
                result = dict(self.full)
        result["session_id"] = f"{session}:{result.get('character_guid') or result.get('character_name')}"
        result["frame_id"] = f"{session}:{kind}:{seq}"
        result["state_age"] = now - self.full_received_at
        result["state_sequence"] = self.last_full
        result["state_sample_time"] = self.full.get("monotonic_time")
        result["state_age"] = max(result["state_age"], float(result.get("monotonic_time") or 0) - float(self.full.get("monotonic_time") or 0))
        result["transport_session"] = session
        result["transport_kind"] = kind
        result["telemetry_lane"] = "FAST_STATE" if kind == "FAST" else "FULL_STATE"
        result["fast_sequence"] = self.last_fast
        result["fast_received_at"] = now if kind == "FAST" else None
        return normalize(result)
