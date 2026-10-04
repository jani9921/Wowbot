from wowbot.agent.memory import AgentMemory
from wowbot.agent.rejection_memory import RejectionMemory


def test_agent_memory_delegates_rejection_to_dedicated_owner(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    try:
        assert isinstance(memory.rejection_memory, RejectionMemory)
        marker = {"source": "WORLD3D", "track_id": "t", "visual_signature": {"hash": "x"}}
        for at in (1., 31., 61.):
            memory.record_rejection(marker, map_id=1409, reason="no_information", at=at)
        assert memory.rejection_status(marker, map_id=1409, at=62.)["belief"] == "REJECTED"
        memory.record_rejection_contradiction(marker, map_id=1409, at=63.)
        contradicted = memory.rejection_status(marker, map_id=1409, at=63.)
        assert contradicted["belief"] == "CANDIDATE"
        assert contradicted["contradictions"] == 1
    finally:
        memory.close()


def test_rejection_owner_expire_query_and_reliability(tmp_path):
    memory = AgentMemory(tmp_path / "memory.sqlite3")
    try:
        marker = {"source": "MINIMAP_CV", "track_id": "m", "visual_signature": {"hash": "y"}}
        memory.rejection_memory.record(marker, map_id=1, reason="empty", at=1., ttl=2.)
        assert memory.rejection_memory.query(marker, map_id=1, at=2.)["belief"] == "SUPPRESSED"
        assert memory.rejection_memory.expire(4.) == 1
        assert memory.rejection_memory.reliability(marker, map_id=1, at=4.) == 1.0
    finally:
        memory.close()
