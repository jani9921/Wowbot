"""Server-first mode (user 2026-10-21: "állítsd át szerver módra").

While Ymir data is fresh, server-driven proposals lead. Input-policy
selection is tested separately: stale health must not re-enable vision.
"""
from types import SimpleNamespace

import pytest

from wowbot.agent.engine_runtime_projection import movement_visual_interrupt
from wowbot.agent.models import Proposal
from wowbot.agent.planner import Planner
from wowbot.agent.server_mode import FRESH_SECONDS, server_driven, server_mode_active, status
from wowbot.agent.world_packet_reducer import WorldPacketReducer


def test_active_only_with_a_fresh_stream_and_server_entities(monkeypatch):
    assert status(3., 12)["active"] is True
    assert status(FRESH_SECONDS + 1., 12) == {**status(FRESH_SECONDS + 1., 12), "active": False,
                                               "reason": "server_stream_stale"}
    assert status(3., 0)["reason"] == "no_server_entities"
    assert status(None, 12)["active"] is False
    monkeypatch.setenv("AIPC_SERVER_MODE", "0")
    assert status(3., 12) == {**status(3., 12), "active": False, "reason": "disabled"}


def test_the_state_carries_the_mode_from_the_packet_stream():
    model = SimpleNamespace(addon_state={}, last_received=100., source_latest={},
                            _packet_status={"last_received_at": 96.})
    state = {"packet_entities": {"Creature-1": {"guid": "Creature-1"}}}
    WorldPacketReducer.project(model, state)
    assert server_mode_active(state) and state["server_mode"]["packet_age"] == 4.
    model._packet_status = {"last_received_at": 60.}
    WorldPacketReducer.project(model, state)
    assert not server_mode_active(state)


SERVER_NPC = Proposal.make("MOVE", "server npc", {"purpose": "APPROACH_SERVER_NPC", "server_entity_guid": "C-1"},
                           priority=102, evidence=("server_npc_position", "objective_names_npc"))
INSPECT = Proposal.make("INSPECT", "hover a box", {"track_id": "t1"}, priority=120)
SEEK = Proposal.make("SEEK_VISUAL_CUE", "seek", {"track_id": "t2"}, priority=110)
REGION = Proposal.make("MOVE", "region", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION"}, priority=90)
TALK = Proposal.make("INTERACT", "talk", {"soft_guid": "C-2"}, priority=80)


def test_in_server_mode_any_server_proposal_silences_screen_and_map_search():
    proposals = [SERVER_NPC, INSPECT, SEEK, REGION, TALK]
    kept = Planner.prefer_server_targets(proposals, server_mode=True)
    assert [p.skill for p in kept] == ["MOVE", "INTERACT"]
    assert kept[0] is SERVER_NPC
    # Explicit vision-first policy: only a kill target leads, as before.
    assert Planner.prefer_server_targets(proposals) == proposals
    # Without a server proposal the quest area is walked; the screen is never
    # searched (live 2026-10-21 10:34-10:35: 45 s of SEEK/INSPECT).
    assert Planner.prefer_server_targets([INSPECT, SEEK, REGION], server_mode=True) == [REGION]
    (wait,) = Planner.prefer_server_targets([INSPECT, SEEK], server_mode=True)
    assert wait.skill == "WAIT" and wait.parameters["reason"] == "server_mode_no_server_option"
    assert Planner.prefer_server_targets([INSPECT, SEEK, REGION]) == [INSPECT, SEEK, REGION]


def test_server_driven_covers_every_server_source():
    assert server_driven(SERVER_NPC)
    assert server_driven(Proposal.make("TARGET", "tab", {"activation_source": "TAB_SERVER_GUID"}))
    assert server_driven(Proposal.make("MOVE", "ender", {"knowledge_priority": "SERVER_LIVE"}))
    assert server_driven(Proposal.make("LOOT", "corpse", {}, evidence=("server_lootable_flag",)))
    assert not server_driven(INSPECT) and not server_driven(REGION)


def test_an_unidentified_box_does_not_stop_a_route_in_server_mode():
    attempt = SimpleNamespace(proposal=Proposal.make(
        "MOVE", "search objective", {"purpose": "LOCATE_QUEST_OBJECTIVE_REGION", "objective_type": "KILL",
                                     "coordinate_space": "WORLD_YARDS", "instance_id": 2175,
                                     "x": 100., "y": 100.}))
    world_state = {
        "monotonic_time": 4.,
        "player_world_position": {"x": 90., "y": 100., "instance_id": 2175},
        "visual_candidates": [{"source": "WORLD3D", "kind": "unknown_subject_candidate", "stable_frames": 6,
                               "lifecycle": "STABLE", "inspectable": True, "observed_at": 4.,
                               "candidate_labels": ["learned_subject_like"], "track_id": "strong",
                               "appearance": {"learned_label_hypothesis": "creature_unit_like"},
                               "confidence": .30}]}
    assert movement_visual_interrupt(attempt, world_state)["track_id"] == "strong"
    server = {**world_state, "server_mode": {"active": True}}
    assert movement_visual_interrupt(attempt, server) is None


DOT = Proposal.make("MOVE", "minimap dot", {"purpose": "APPROACH_MINIMAP_QUEST_DOT"}, priority=95)
FLOOR = Proposal.make("MOVE", "floor arrow", {"purpose": "APPROACH_MINIMAP_OTHER_FLOOR_OBJECTIVE"}, priority=94)
MAP = Proposal.make("OPEN_MAP", "map scan", {}, priority=93)
BOX = Proposal.make("VISUAL_APPROACH", "3D box", {"purpose": "COMBAT"}, priority=105)


def test_server_mode_drops_every_screen_derived_step():
    """User 2026-10-21 16:10: "sárga pötty a minimapon odamegyek? vizuális jel
    fel-le? nem lettek ezek kikapcsolva?"."""
    kept = Planner.prefer_server_targets([DOT, FLOOR, MAP, BOX, REGION, TALK], server_mode=True)
    assert kept == [REGION, TALK]
    assert Planner.prefer_server_targets([DOT, FLOOR, MAP, BOX]) == [DOT, FLOOR, MAP, BOX]
    assert all(Planner.vision_driven(p) for p in (DOT, FLOOR, MAP, BOX, INSPECT, SEEK))
    assert not any(Planner.vision_driven(p) for p in (SERVER_NPC, REGION, TALK))


def test_server_mode_withholds_pointer_moves_onto_screen_tracks():
    """User 2026-10-21 16:15: "az egeret is húzogatja rá a trackekre"."""
    from wowbot.agent.models import Command
    from wowbot.execution.command_dispatch import CommandDispatcher

    class Executor:
        def __init__(self):
            self.sent = []

        def execute(self, commands):
            self.sent.extend(commands)
    executor = Executor()
    active = {"on": True}
    dispatcher = CommandDispatcher(executor, pointer_gate=lambda: active["on"])
    hover, pan = Command("HOVER", x=.5, y=.5), Command("CAMERA_PAN", x=.6, y=.4)
    row, key = Command("CLICK", x=.12, y=.62), Command("BIND", "INTERACTTARGET")
    assert dispatcher.dispatch((hover,)) is None
    dispatcher.dispatch((hover, row, pan, key))
    assert executor.sent == [row, key] and dispatcher.withheld_pointer_commands == 3
    active["on"] = False                                          # vision-first again
    dispatcher.dispatch((hover,))
    assert executor.sent[-1] is hover
