"""Live 2026-10-07 11:13 (pid 15440, addon 0.9.59, "Who Lurks in the Pit").

The paged STATE stalled 21 s (state_sequence 1037 from 757437 to 757458).
Every live FAST packet was a bounded variant without ``quest_digest`` or
``ui_error``, so the cocoon credit (1/5 -> 2/5) and "You are too far away."
reached the agent only with the next snapshot: OBJECT_USE failed with
QUEST_CREDIT_NOT_RECEIVED 1.2 s before the credit arrived, and a second
click went out before the out-of-range error was visible.
"""
import json

from adapters.telemetry_packets import PacketAssembler
from test_agent_transport import lua_runtime
from test_fast_world_position import LIVE_LIKE_FAST, _fast_body
from wowbot.verification.quest import QuestProgressVerifier, fast_digest_progress


def test_bounded_fast_packet_carries_the_quest_digest_when_it_fits():
    body = _fast_body(lua_runtime(), LIVE_LIKE_FAST)
    assert "falling" not in body["movement"]                 # still a bounded variant
    assert body["quest_digest"] == [{"complete": False, "done": 0, "id": 55122, "need": 6}]
    assert body["player_world_position"]["x"] == -405.73


def test_bounded_fast_packet_carries_a_fresh_ui_error_first():
    sample = LIVE_LIKE_FAST.replace(
        "player_present=true", "player_present=true,ui_error='You are too far away.',"
        "ui_error_at=356196.5,ui_error_code=289,ui_error_sequence=7")
    body = _fast_body(lua_runtime(), sample)
    assert (body["ui_error"], body["ui_error_code"], body["ui_error_at"]) == (
        "You are too far away.", 289, 356196.5)
    assert body["mouseover"]["name"] == "Quartermaster Richter"


def test_an_oversized_digest_is_left_out_instead_of_evicting_control_fields():
    many = ",".join("{id=%d,complete=false,done=1,need=6}" % (55000+i) for i in range(25))
    sample = LIVE_LIKE_FAST.replace("quest_digest={{id=55122,complete=false,done=0,need=6}}",
                                    "quest_digest={" + many + "}")
    body = _fast_body(lua_runtime(), sample)
    assert "quest_digest" not in body and body["player_world_position"]["instance_id"] == 2175


def test_fast_digest_reaches_the_world_payload():
    assembler = PacketAssembler()
    assembler.feed('AIPC5|s|1|0|1|STATE|{"monotonic_time":1,"character_guid":"Player-1",'
                   '"active_quests":[{"quest_id":55639,"objectives":[{"current":1,"required":5}]}]}', 1)
    fast = assembler.feed('AIPC5|s|2|0|1|FAST|' + json.dumps(
        {"monotonic_time": 2, "quest_digest": [{"id": 55639, "complete": False, "done": 2, "need": 5}],
         "ui_error": "You are too far away.", "ui_error_at": 1.9, "ui_error_code": 289}), 2)
    assert fast["quest_digest"][0]["done"] == 2 and fast["accepted_quest_ids"] == [55639]
    assert fast["ui_error"] == "You are too far away."


def _quest(current, required=5, quest_id=55639, objectives=1):
    return {"quest_id": quest_id, "objectives": [
        {"objective_id": str(index), "current": current if index == 0 else 0, "required": required}
        for index in range(objectives)]}


def _digest(done, quest_id=55639, need=5):
    return [{"id": quest_id, "complete": False, "done": done, "need": need}]


def test_cocoon_credit_is_verified_from_the_fast_digest_before_the_snapshot():
    before = {"active_quests": [_quest(1)], "quest_digest": _digest(1)}
    after = {"active_quests": [_quest(1)], "quest_digest": _digest(2)}    # snapshot still 1/5
    result = QuestProgressVerifier().evaluate(before, after, quest_ids=(55639,),
                                              objective_ids=("55639:0",))
    assert result.success and "quest_digest_progress:55639" in result.evidence


def test_without_a_baseline_or_against_a_newer_snapshot_the_digest_claims_nothing():
    assert fast_digest_progress({}, {"quest_digest": _digest(2)}, (55639,)) == []
    stale = {"active_quests": [_quest(2)], "quest_digest": _digest(1)}   # snapshot newer than digest
    assert fast_digest_progress(stale, {"quest_digest": _digest(2)}, (55639,)) == []
    assert fast_digest_progress(stale, {"quest_digest": _digest(3)}, (55639,)) == ["55639"]


def test_multi_objective_digest_progress_does_not_credit_a_specific_objective():
    before = {"active_quests": [_quest(1, objectives=2)], "quest_digest": _digest(1)}
    after = {"active_quests": [_quest(1, objectives=2)], "quest_digest": _digest(2)}
    result = QuestProgressVerifier().evaluate(before, after, quest_ids=(55639,),
                                              objective_ids=("55639:0",))
    assert not result.success


def test_reappearing_accepted_ids_are_not_a_quest_acceptance():
    """A snapshot newer than the last FAST sample has no accepted ids."""
    before = {"active_quests": [_quest(1)]}
    after = {"active_quests": [_quest(1)], "accepted_quest_ids": [55639]}
    assert not QuestProgressVerifier().evaluate(before, after, quest_ids=(55639,)).success
    real = QuestProgressVerifier().evaluate({"active_quests": [], "accepted_quest_ids": []},
                                            {"active_quests": [], "accepted_quest_ids": [55639]},
                                            quest_ids=(55639,))
    assert real.success and "quest_accepted:55639" in real.evidence


def test_object_use_waits_for_a_snapshot_newer_than_the_use_for_up_to_25_s():
    from wowbot.skills.object_use import ObjectUseSkill
    skill = ObjectUseSkill()
    context = {"used_at": 100.}
    stalled = {"state_sample_time": 99.}
    assert skill._credit_snapshot_pending(context, stalled, 120., 100.)      # 20 s after deadline
    assert not skill._credit_snapshot_pending(context, stalled, 126., 100.)
    assert not skill._credit_snapshot_pending(context, {"state_sample_time": 101.5}, 101., 100.)
