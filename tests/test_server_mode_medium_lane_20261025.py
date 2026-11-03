"""Server mode drops medium-lane work nothing uses any more (user 2026-10-25).

Live 17:26-17:30 the medium tick held the engine lock 0.1-0.45 s (seconds at
times) and the fast flight loop skipped ~half its samples: EntityMemory
objective hypotheses waited for the visual-recognition worker's lock (~31 %
of the agent thread), the diagnostics-only memory metrics ran 6 s once.
"""
from test_packet_agent_bridge import addon
from wowbot.agent import server_mode
from wowbot.agent.models import Observation
from wowbot.agent.world import WorldModel


class CountingMemory:
    def __init__(self):
        self.calls = 0

    def find_by_name(self, *args, **kwargs):
        self.calls += 1
        return []

    def locations(self, *args, **kwargs):
        self.calls += 1
        return []

    def __getattr__(self, name):
        return lambda *args, **kwargs: []


def quests():
    return [{"quest_id": 1, "title": "Q", "is_complete": False,
             "objectives": [{"description": "0/3 Wolf slain", "type": "KILL", "current": 0, "total": 3}]}]


def test_objective_hypotheses_skip_entity_memory_in_server_mode(monkeypatch):
    for selected, expect_calls in ((False, True), (True, False)):
        monkeypatch.setattr(server_mode, "server_mode_selected", lambda state, value=selected: value)
        world = WorldModel()
        memory = CountingMemory()
        world.entity_memory = memory
        world.ingest(Observation.create(addon(active_quests=quests()), 9.))
        assert (memory.calls > 0) is expect_calls, selected
