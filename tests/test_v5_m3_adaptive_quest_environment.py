"""Adaptive M3/M6 quest acceptance environment.

Unlike the legacy JSONL replay, this environment does not publish a fixed
sequence of observations.  It observes the skill actually selected by the
agent and only then exposes the corresponding authoritative game outcome.
An incorrect decision therefore cannot accidentally advance the scenario.
"""
from copy import deepcopy

from test_agent_core import agent, state


QUEST_ID = 701
FOLLOW_UP_ID = 702
ENEMY_GUID = "Creature-adaptive-enemy"
GIVER_GUID = "Creature-adaptive-giver"


class AdaptiveQuestEnvironment:
    def __init__(self):
        self.phase = "OFFER"
        self.now = 1.0
        self.event_sequence = 0
        self.events = []
        self.position = {"x": .20, "y": .20}
        self.skills = []
        self.interaction_attempts = 0

    @staticmethod
    def _objective(current=0):
        return {"objective_id": f"{QUEST_ID}:loot", "raw_type": "item",
                "type": "COLLECT", "description": "Training token collected",
                "current": current, "required": 1,
                "is_complete": current >= 1}

    def _quest(self, current=0):
        return {"quest_id": QUEST_ID, "title": "Adaptive Trial",
                "is_campaign": True, "is_complete": current >= 1,
                "waypoint": {"map_id": 1609, "x": .60, "y": .60},
                "objectives": [self._objective(current)]}

    def _event(self, kind, payload):
        self.event_sequence += 1
        self.events = [{"sequence": self.event_sequence, "timestamp": self.now,
                        "event_type": kind, "payload": payload}]

    def observation(self):
        common = dict(
            event_sequence=self.event_sequence, events=deepcopy(self.events),
            position=deepcopy(self.position),
        )
        if self.phase == "OFFER":
            return state(self.now, **common, quest_ui={
                "open": True, "action": "ACCEPT", "quest_id": QUEST_ID,
                "x": .30, "y": .30,
            })
        if self.phase in {"TRAVEL", "ENEMY", "COMBAT"}:
            target = None
            in_combat = False
            actionbar = []
            if self.phase in {"ENEMY", "COMBAT"}:
                target = {"guid": ENEMY_GUID, "name": "Training Murloc",
                          "health": 10, "attackable": True, "dead": False}
                in_combat = True
                actionbar = [{"kind": "spell", "id": 100,
                              "action": "ACTIONBUTTON1", "is_usable": True,
                              "is_harmful": True, "cooldown_remaining": 0,
                              "in_range": True}]
            return state(self.now, **common, active_quests=[self._quest()],
                         target=target, is_in_combat=in_combat,
                         actionbar=actionbar)
        if self.phase == "CORPSE":
            return state(self.now, **common, active_quests=[self._quest()],
                         target={"guid": ENEMY_GUID, "name": "Training Murloc",
                                 "health": 0, "attackable": True, "dead": True},
                         loot_pending=True)
        if self.phase in {"RETURN", "TALKED"}:
            quest_ui = {"open": False, "entries": []}
            if self.phase == "TALKED":
                quest_ui = {"open": True, "action": "COMPLETE",
                            "quest_id": QUEST_ID, "x": .32, "y": .31}
            return state(self.now, **common, active_quests=[self._quest(1)],
                         target={"guid": GIVER_GUID, "name": "Quest Captain",
                                 "attackable": False,
                                 "quest_role": "QUEST_TURN_IN"},
                         inventory={"items": [{"item_id": 9001, "count": 1}],
                                    "free_slots": 9}, quest_ui=quest_ui)
        if self.phase == "FOLLOW_UP":
            return state(self.now, **common, active_quests=[{
                "quest_id": FOLLOW_UP_ID, "title": "Adaptive Follow-up",
                "is_campaign": True, "dependencies": [str(QUEST_ID)],
                "objectives": [],
            }])
        raise AssertionError(f"unknown adaptive phase: {self.phase}")

    def react(self, skill):
        self.skills.append(skill)
        self.events = []
        if self.phase == "OFFER" and skill == "QUEST_DIALOG":
            self.phase = "TRAVEL"
            self._event("QUEST_ACCEPTED", {"quest_id": QUEST_ID})
        elif self.phase == "TRAVEL" and skill in {"MOVE", "REACH_LOCATION"}:
            self.position = {"x": .60, "y": .60}
            self.phase = "ENEMY"
        elif self.phase in {"ENEMY", "COMBAT"} and skill in {"COMBAT", "DEFEND"}:
            self.phase = "CORPSE"
            self._event("UNIT_DIED", {"guid": ENEMY_GUID})
        elif self.phase == "CORPSE" and skill == "LOOT":
            self.phase = "RETURN"
            self.position = {"x": .20, "y": .20}
            self._event("LOOT_RECEIVED", {"source_guid": ENEMY_GUID,
                                           "item_id": 9001})
        elif self.phase == "RETURN" and skill in {"TALK", "INTERACT"}:
            self.interaction_attempts += 1
            if self.interaction_attempts == 1:
                # Induced M6 recovery: the first click yields no dialog.  Move
                # time beyond the skill deadline so the production verifier,
                # failure manager and planner must terminate/retry it.
                self.now += 9.0
                return
            self.phase = "TALKED"
        elif self.phase == "TALKED" and skill == "QUEST_DIALOG":
            self.phase = "FOLLOW_UP"
            self._event("QUEST_TURNED_IN", {"quest_id": QUEST_ID})
        self.now += .5


def test_agent_completes_adaptive_quest_and_discovers_follow_up():
    bot, executor = agent("Questelj", {"mode": "MAIN_CAMPAIGN"})
    environment = AdaptiveQuestEnvironment()
    trace = []

    # The bound is an acceptance criterion: no unbounded WAIT/INSPECT/replan
    # loop may hide a missing skill transition.
    for _ in range(40):
        status = bot.tick(environment.observation(), environment.now)
        skill = (status.get("decision") or {}).get("skill")
        trace.append({"phase": environment.phase, "skill": skill,
                      "result": deepcopy(status.get("result") or {})})
        environment.react(skill)
        if environment.phase == "FOLLOW_UP":
            # One final observation lets the quest model retain both the
            # verified turn-in history and the newly discovered campaign step.
            final = bot.tick(environment.observation(), environment.now)
            break
    else:
        raise AssertionError(
            f"adaptive quest did not finish; phase={environment.phase}, "
            f"skills={environment.skills}"
        )

    required = {"QUEST_DIALOG", "LOOT"}
    assert required <= set(environment.skills)
    assert any(skill in {"COMBAT", "DEFEND"} for skill in environment.skills)
    assert any(skill in {"MOVE", "REACH_LOCATION"}
               for skill in environment.skills)
    assert any(skill in {"TALK", "INTERACT"} for skill in environment.skills)
    assert environment.phase == "FOLLOW_UP"
    assert environment.interaction_attempts >= 2
    assert any(row["result"].get("outcome") == "FAILURE" for row in trace)
    first_failure = next(index for index, row in enumerate(trace)
                         if row["result"].get("outcome") == "FAILURE")
    assert any(row["skill"] in {"TALK", "INTERACT", "QUEST_DIALOG"}
               for row in trace[first_failure + 1:])
    assert bot.world.quest_model.records[QUEST_ID].lifecycle_state.value == "TURNED_IN"
    assert FOLLOW_UP_ID in bot.world.quest_model.records
    assert bot.world.quest_model.records[FOLLOW_UP_ID].raw["is_campaign"] is True
    assert executor.commands  # Real skill execution reached the recording sink.
    assert final["mode"] == "FULL_AI"
