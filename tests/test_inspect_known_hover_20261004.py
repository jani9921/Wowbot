"""Live 2026-10-04 19:36: Quartermaster Richter (target, track 9), Captain
Garrick (track 11) and Private Cole (track 51) were hovered in turn four times
in ~25 s; every hover had already named them (user: "4x egymás után körbe-körbe
ment ugyanarra a 3 npc-re")."""
from types import SimpleNamespace

from wowbot.agent.visual_inspection_planning import VisualInspectionPolicy

RICHTER = "Creature-0-1463-2175-58799-156800-0000C2113D"
GARRICK = "Creature-0-1463-2175-58799-245394-000042113D"


def _world(x=0., facing=0., result=None, mouseover=None, target=None, ready=(), quests=({"quest_id": 1},)):
    return SimpleNamespace(
        state={"player_world_position": {"x": x, "y": 0.}, "orientation": facing,
               "mouseover": mouseover or {}, "target": target or {}, "active_quests": list(quests)},
        runtime_context={"last_result": result or {}},
        quest_model=SimpleNamespace(ready=lambda: list(ready)))


def _hover(policy, key, track, x, guid, name, at, **extra):
    policy.__dict__.setdefault("_inspect_points", {})[key] = {
        "x": x, "y": .5, "view": (0., 0., 0.), "track_id": track}
    done = {"skill": "INSPECT", "action_id": f"a-{key}", "key": key,
            "reason": "expected_observation_verified"}
    policy._note_inspect_outcome(_world(result=done, mouseover={"guid": guid, "name": name, **extra}), at)


def test_named_unneeded_npcs_and_the_target_are_not_hovered_again():
    policy = VisualInspectionPolicy()
    _hover(policy, "k1", "WORLD3D:11", .41, GARRICK, "Captain Garrick", 10.)
    _hover(policy, "k2", "WORLD3D:9", .61, RICHTER, "Quartermaster Richter", 11., quest_related=True)
    selected = _world(target={"guid": RICHTER, "name": "Quartermaster Richter"})
    # Garrick: named, no objective needs him -> skipped by track and by spot.
    assert policy._known_unneeded(selected, .70, .30, "WORLD3D:11")
    assert policy._known_unneeded(selected, .41, .50, None)
    # Richter is already the target -> nothing to learn by hovering her.
    assert policy._known_unneeded(selected, .61, .50, "WORLD3D:9")
    # Not yet selected, her tooltip lists an open objective -> hover allowed.
    assert not policy._known_unneeded(_world(), .61, .50, "WORLD3D:9")
    # Unknown tracks are still inspected.
    assert not policy._known_unneeded(selected, .20, .50, "WORLD3D:51")
    # After the memory window the unit may be checked again.
    policy._note_inspect_outcome(_world(), 75.)
    assert not policy._known_unneeded(selected, .41, .50, "WORLD3D:11")


def test_a_named_npc_an_objective_needs_stays_inspectable():
    policy = VisualInspectionPolicy()
    _hover(policy, "k1", "WORLD3D:11", .41, GARRICK, "Captain Garrick", 10.)
    talk = SimpleNamespace(type="TALK_TO", target_entity={"name": "Captain Garrick"},
                           raw={}, description="Speak with Captain Garrick")
    assert not policy._known_unneeded(_world(ready=[talk]), .41, .50, "WORLD3D:11")


def test_not_needed_holds_only_for_the_quest_state_it_was_judged_in():
    """Live 2026-10-05 05:38: Captain Garrick was named while the vendor quest
    was open; when it completed he was the turn-in NPC but stayed skipped."""
    policy = VisualInspectionPolicy()
    open_quest = ({"quest_id": 55194, "is_complete": False,
                   "objectives": [{"current": 0, "is_complete": False}]},)
    done_quest = ({"quest_id": 55194, "is_complete": True,
                   "objectives": [{"current": 1, "is_complete": True}]},)
    policy.__dict__.setdefault("_inspect_points", {})["k1"] = {
        "x": .41, "y": .5, "view": (0., 0., 0.), "track_id": "WORLD3D:11"}
    done = {"skill": "INSPECT", "action_id": "a-k1", "key": "k1", "reason": "expected_observation_verified"}
    policy._note_inspect_outcome(_world(result=done, quests=open_quest,
                                        mouseover={"guid": GARRICK, "name": "Captain Garrick"}), 10.)
    assert policy._known_unneeded(_world(quests=open_quest), .41, .50, "WORLD3D:11")
    assert not policy._known_unneeded(_world(quests=done_quest), .41, .50, "WORLD3D:11")


def test_verdict_expires_when_the_player_moves_or_searches_for_a_giver():
    """Live 2026-10-05 05:39: Private Cole was judged from afar; at the API
    '!' spot where he stood he was never hovered again (user)."""
    policy = VisualInspectionPolicy()
    _hover(policy, "k1", "WORLD3D:1", .30, "Creature-0-1-2-3-156803-1", "Private Cole", 10.)
    assert policy._known_unneeded(_world(), .30, .50, "WORLD3D:1")
    # Walked 12 yd towards the quest-giver pin: judge him again there.
    assert not policy._known_unneeded(_world(x=12.), .30, .50, "WORLD3D:1")
    # No active quest: any friendly may be the next giver -> never skipped.
    assert not policy._known_unneeded(_world(quests=()), .30, .50, "WORLD3D:1")
