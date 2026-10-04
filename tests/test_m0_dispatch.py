from wowbot.runtime import M0SkillDispatcher


def test_dispatcher_declares_the_migrated_canonical_skill_surface():
    assert M0SkillDispatcher.handles("TARGET")
    assert M0SkillDispatcher.handles("LOOT")
    # M1 dialog clicks share the one active-skill lifecycle and are no longer
    # executed through the legacy generic registry verifier.
    assert M0SkillDispatcher.handles("QUEST_DIALOG")
    assert M0SkillDispatcher.handles("EXTRA_ACTION")
    assert M0SkillDispatcher.handles("USE_ON_TARGET")
    assert M0SkillDispatcher.handles("ASSIST")
    assert M0SkillDispatcher.handles("FOLLOW_INSTRUCTION")
    assert M0SkillDispatcher.handles("OBJECT_USE")
