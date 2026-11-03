"""REV4 P8.4 WITNESS: a watched conversation's end is the credit or silence.

"Listen to / overhear" objectives credit at the end of a conversation we only
watch; no talk of ours starts it.  While a named speaker talks the agent
stays (WAIT_EVENT above the approach/sweep moves); the credit, 20 s of
silence or the 90 s cap ends it.  Other speakers start nothing."""
from wowbot.agent.objective_speech_planning import ObjectiveSpeechHold


def state(now, lines=(), done=False, combat=False):
    return {"monotonic_time": now, "is_in_combat": combat, "quest_ui": {"open": False},
            "active_quests": [{"quest_id": 500, "is_complete": False, "objectives": [
                {"description": f"{int(done)}/1 Overhear the conversation", "is_complete": done}]}],
            "reference_knowledge": {"quests": {"500": {"objectives": [
                {"description": "Overhear the conversation", "mechanism": "WITNESS",
                 "named_creatures": [{"entry": 1, "name": "Captain Danuvin"},
                                     {"entry": 2, "name": "Scout Galiaan"}]}]}}},
            "events": [{"event_type": "NPC_INSTRUCTION", "sequence": index,
                        "payload": {"sender": sender, "message": f"line {index}"}}
                       for index, sender in lines]}


def test_the_named_speakers_hold_the_agent_until_credit_or_silence():
    hold = ObjectiveSpeechHold()
    assert hold.propose(state(0.)) == []                           # nothing said yet
    (wait,) = hold.propose(state(1., lines=[(1, "Captain Danuvin")]))
    assert wait.skill == "WAIT_EVENT" and wait.parameters["objective_kind"] == "WITNESS_CONVERSATION"
    assert wait.priority == 121
    assert hold.propose(state(15., lines=[(2, "Scout Galiaan")]))   # the other one answers
    assert hold.propose(state(35.5, lines=[(2, "Scout Galiaan")])) == []  # 20 s silence: over
    hold.propose(state(40., lines=[(3, "Captain Danuvin")]))
    assert hold.propose(state(41., lines=[(3, "Captain Danuvin")], done=True)) == []   # credited


def test_other_speakers_combat_and_the_cap():
    hold = ObjectiveSpeechHold()
    assert hold.propose(state(1., lines=[(1, "Defias Thug")])) == []
    assert hold.propose(state(2., lines=[(2, "Captain Danuvin")], combat=True)) == []
    capped = ObjectiveSpeechHold()
    at, seq = 0., 0
    while at < 100.:
        seq += 1
        result = capped.propose(state(at, lines=[(seq, "Captain Danuvin")]))
        at += 10.
    assert result == []                                           # 90 s cap


CONVERSATION = "Conversation-0-1463-2444-79-25590-00006A0001"


def talking(now, *, live=True, done=False, entry=25590, guid=CONVERSATION):
    value = state(now, done=done)
    value["packet_entities"] = {guid: {"guid": guid, "kind": "CONVERSATION", "entry_id": entry,
                                       "info": {"sampled_at": now}, **({} if live else {"removed": {"reason": "DESTROYED"}})}}
    return value


def test_a_running_server_conversation_holds_until_its_object_is_removed():
    hold = ObjectiveSpeechHold()
    (wait,) = hold.propose(talking(0.))
    assert wait.parameters["objective_kind"] == "CONVERSATION" and wait.parameters["conversation_entry"] == 25590
    assert hold.propose(talking(30.))                                  # still running, no line needed
    assert hold.propose(talking(31., live=False)) == []                # removed: the end signal


def test_the_credit_relation_is_learned_per_conversation_entry():
    hold = ObjectiveSpeechHold()
    hold.propose(talking(0.))
    hold.propose(talking(10., live=False))
    hold.propose(talking(16., live=False))                             # no credit within the grace
    assert hold.conversation_credit[25590] == "NO_CREDIT"
    later = "Conversation-0-1463-2444-79-25590-00006A0002"
    assert hold.propose(talking(100., guid=later)) == []               # learned: not awaited again
    early = ObjectiveSpeechHold()
    early.propose(talking(0., entry=7))
    early.propose(talking(2., entry=7, done=True))                    # "only one line": credit while it runs
    assert early.conversation_credit[7] == "CREDIT_BEFORE_END"
    at_end = ObjectiveSpeechHold()
    at_end.propose(talking(0., entry=8))
    at_end.propose(talking(9., entry=8, live=False))
    at_end.propose(talking(11., entry=8, live=False, done=True))
    assert at_end.conversation_credit[8] == "CREDIT_AT_END"


def test_a_conversation_is_never_awaited_past_the_cap():
    hold = ObjectiveSpeechHold()
    hold.propose(talking(0.))
    value = talking(61.)
    value["packet_entities"][CONVERSATION]["info"]["sampled_at"] = 0.
    assert hold.propose(value) == []


def test_conversation_guids_and_creates_are_recognised_by_the_packet_layer():
    from wowbot.packetio.context import addon_entity_guid
    from wowbot.packetio.pkt import entity_guid_kind
    high = (7 << 58) | (1463 << 42) | (2444 << 29) | (25590 << 6)
    raw = f"{high:016X}{(79 << 40) | 0x6A0001:016X}"
    assert entity_guid_kind(raw) == ("CONVERSATION", 25590)
    assert addon_entity_guid(raw) == "Conversation-0-1463-2444-79-25590-00006A0001"
