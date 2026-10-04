"""User 2026-10-04: use the local LLM (Ollama) to read quest text, ability
tooltips and NPC speech -- asked once, cached, constrained, and always
subordinate to addon facts and observed outcomes."""
import time

from wowbot.agent.models import Observation
from wowbot.agent.quest_model import QuestModel
from wowbot.agent.semantic_advisor import (SemanticAdvisor, copied_name, quest_request,
                                           speech_request, update_world, validate_quest,
                                           validate_speech)
from wowbot.agent.vehicle_abilities import CLOSE, TARGETED, ability_mode, choose_attack_action
from wowbot.agent.world import WorldModel


def _settle(advisor):
    for _ in range(200):
        advisor.poll()
        if advisor.future is None and not advisor.queue:
            return
        time.sleep(.01)


def test_names_must_be_copied_from_the_game_text():
    assert copied_name("Wild Boars", "0/3 Use the Re-Sizer on Wild Boar") == "Wild Boars"
    assert copied_name("Stormwind Guard", "0/8 Monstrous Cadaver slain") is None
    assert copied_name("null", "anything") is None
    payload = {"quest": "Q", "description": "", "objectives_text": "",
               "objectives": {"o1": "Monstrous Cadaver slain"}}
    result = validate_quest(payload, {"o1": {"action": "SMASH", "target": "Hogger", "item": None}})
    assert result["objectives"]["monstrous cadaver slain"] == {
        "action": "UNKNOWN", "target": None, "item": None, "vehicle": None, "text": "Monstrous Cadaver slain"}


def test_answers_are_cached_on_disk_and_asked_once(tmp_path):
    calls = []

    def fake(system, payload, config):
        calls.append(payload)
        return {"o1": {"action": "RIDE_VEHICLE", "target": "Mechanical Strider", "item": None,
                       "vehicle": "Mechanical Strider"}}

    quest = {"quest_id": 7, "title": "Strider Run", "objectives": [
        {"description": "0/1 Climb onto the Mechanical Strider", "raw_type": "monster", "type": "KILL"}]}
    key, payload = quest_request(quest)
    advisor = SemanticAdvisor({"enabled": True}, tmp_path / "cache.json", transport=fake)
    assert advisor.ask("quest", key, payload) is None
    _settle(advisor)
    answer = advisor.ask("quest", key, payload)
    assert answer["objectives"]["climb onto the mechanical strider"]["action"] == "RIDE_VEHICLE"
    reloaded = SemanticAdvisor({"enabled": True}, tmp_path / "cache.json", transport=fake)
    assert reloaded.ask("quest", key, payload) == answer and len(calls) == 1
    # Progress does not change the question.
    progressed = {**quest, "objectives": [{**quest["objectives"][0], "description": "1/1 Climb onto the Mechanical Strider"}]}
    assert quest_request(progressed)[0] == key


def test_unreachable_server_backs_off_without_raising(tmp_path):
    def down(system, payload, config):
        raise ConnectionRefusedError("no ollama")

    advisor = SemanticAdvisor({"enabled": True, "unavailable_backoff_seconds": 60}, None, transport=down)
    advisor.ask("quest", "k", {"objectives": {}})
    _settle(advisor)
    assert advisor.status == "unavailable" and advisor.metrics["failed"] == 1
    advisor.ask("quest", "k2", {"objectives": {}})
    advisor.poll()
    assert advisor.future is None          # still backing off
    assert SemanticAdvisor({"enabled": False}).ask("quest", "k", {}) is None


def _objective(model, quest_id=7):
    return model.records[quest_id].objectives[0]


def test_hint_turns_a_ridden_monster_objective_into_an_npc_interaction():
    model = QuestModel()
    quest = {"quest_id": 7, "title": "Strider Run", "objectives": [
        {"description": "0/1 Climb onto the Mechanical Strider", "raw_type": "monster", "type": "KILL",
         "current": 0, "required": 1}]}
    model.ingest([quest], "o", 1.)
    assert _objective(model).type == "KILL"
    model.semantic_hints = {("7", "climb onto the mechanical strider"): {
        "action": "RIDE_VEHICLE", "target": "Mechanical Strider", "item": None, "source": "LLM_SEMANTIC"}}
    model.ingest([quest], "o2", 2.)
    objective = _objective(model)
    assert objective.type == "INTERACT_NPC"
    assert objective.target_entity == {"npc_id": None, "name": "Mechanical Strider", "source": "LLM_OBJECTIVE_TEXT"}
    assert any(item.get("source") == "LLM_SEMANTIC" for item in objective.semantic_candidates)


def test_hint_never_overrides_a_kill_with_a_kill_and_fills_unknown():
    model = QuestModel()
    model.semantic_hints = {
        ("8", "monstrous cadaver slain"): {"action": "USE_VEHICLE_ABILITY", "target": "Monstrous Cadaver"},
        ("9", "calibrate the device"): {"action": "INTERACT_OBJECT", "target": None, "item": None}}
    model.ingest([
        {"quest_id": 8, "objectives": [{"description": "0/8 Monstrous Cadaver slain", "raw_type": "monster",
                                        "type": "KILL", "current": 0, "required": 8}]},
        {"quest_id": 9, "objectives": [{"description": "Calibrate the device", "raw_type": "progressbar",
                                        "current": 0, "required": 1}]}], "o", 1.)
    kill = _objective(model, 8)
    assert kill.type == "KILL" and kill.semantic_hint["action"] == "USE_VEHICLE_ABILITY"
    assert kill.target_entity["name"] == "Monstrous Cadaver"
    assert _objective(model, 9).type == "INTERACT"


def test_learned_effect_beats_llm_beats_keywords():
    action = {"id": 7, "name": "Gorge", "max_range": 0}
    assert ability_mode(action) == CLOSE
    assert ability_mode(action, advice={"7": {"mode": "TARGETED"}}) == TARGETED
    assert ability_mode(action, {"7": {"mode": "FORWARD_DASH"}}, {"7": {"mode": "TARGETED"}}) == "FORWARD_DASH"
    state = {"vehicle_controls": True, "actionbar": [
        {"action": "ACTIONBUTTON1", "id": 7, "name": "Gorge", "source": "VEHICLE_BAR"},
        {"action": "ACTIONBUTTON2", "id": 8, "name": "Blast", "source": "VEHICLE_BAR"}]}
    assert choose_attack_action(state, advice={"7": {"mode": "SELF_BUFF"}})["id"] == 8


def test_speech_keeps_only_known_abilities_and_copied_targets():
    request = speech_request({"payload": {"sender": "Lindie Springstock",
                                          "message": "The re-sizer can enlarge one of the nearby boars so it "
                                                     "can trample all of those monsters flat!"}},
                             {"55879:1": "Monstrous Cadaver slain"}, ["Trample", "Charge"])
    key, payload = request
    result = validate_speech(payload, {"instruction": True, "action": "USE_ABILITY", "ability": "trample",
                                       "target": "Monstrous Cadaver", "objective": "55879:1"})
    assert result["ability"] == "Trample" and result["target"] == "Monstrous Cadaver"
    assert result["objective"] == "Monstrous Cadaver slain"
    invented = validate_speech(payload, {"instruction": True, "ability": "Fireball", "target": "Hogger"})
    assert invented["ability"] is None and invented["target"] is None


def test_update_world_publishes_hints_to_the_quest_model(tmp_path):
    def fake(system, payload, config):
        if "objectives" in payload and isinstance(payload["objectives"], dict) and "quest" in payload:
            return {"o1": {"action": "RIDE_VEHICLE", "target": "Mechanical Strider"}}
        return {}

    world = WorldModel()
    world.ingest(Observation.create({
        "session_id": "s", "timestamp": 1., "frame_id": "f", "monotonic_time": 1., "map_id": 1,
        "orientation": 0., "position": {"x": .5, "y": .5}, "player_present": True,
        "active_quests": [{"quest_id": 7, "title": "Strider Run", "objectives": [
            {"description": "0/1 Climb onto the Mechanical Strider", "raw_type": "monster", "type": "KILL",
             "current": 0, "required": 1}]}],
        "quest_text": {"quest_id": 7, "description": "Hop on the strider and ride it to the camp."}}, 1.))
    assert world.quest_texts["7"]["description"].startswith("Hop on")
    advisor = SemanticAdvisor({"enabled": True}, tmp_path / "c.json", transport=fake)
    update_world(advisor, world, 1.)
    _settle(advisor)
    update_world(advisor, world, 2.)
    assert world.quest_model.records[7].objectives[0].type == "INTERACT_NPC"
    assert world.state["semantic_advice"]["objective_hints"] == 1


def test_only_complex_quests_are_interpreted():
    from wowbot.agent.semantic_advisor import quest_needs_interpretation
    simple = {"quest_id": 1, "objectives": [
        {"description": "0/7 Quilboar slain", "raw_type": "monster"},
        {"description": "0/5 Raw Meat collected", "raw_type": "item"}]}
    boar = {"quest_id": 2, "objectives": [
        {"description": "Ride the Giant Boar", "raw_type": "monster"},
        {"description": "0/8 Monstrous Cadaver slain", "raw_type": "monster"}]}
    item = {**simple, "special_item": {"item_id": 170557}}
    assert not quest_needs_interpretation(simple)
    assert quest_needs_interpretation(boar) and quest_needs_interpretation(item)
    assert not quest_needs_interpretation({**boar, "is_complete": True})


def test_complex_quest_hint_corrects_the_coarse_api_type():
    model = QuestModel()
    quest = {"quest_id": 11, "objectives": [
        {"description": "0/5 Injured Soldier bandaged", "raw_type": "monster", "type": "KILL",
         "current": 0, "required": 5}]}
    hint = {"action": "USE_ITEM_ON_TARGET", "target": "Injured Soldier", "item": "First Aid Kit"}
    model.semantic_hints = {("11", "injured soldier bandaged"): hint}
    model.ingest([quest], "o", 1.)
    assert _objective(model, 11).type == "KILL"           # simple-quest hint: advisory only
    model.semantic_hints = {("11", "injured soldier bandaged"): {**hint, "complex_quest": True}}
    model.ingest([quest], "o2", 2.)
    objective = _objective(model, 11)
    assert objective.type == "USE_ITEM_ON_TARGET"
    assert objective.target_object["name"] == "First Aid Kit"
