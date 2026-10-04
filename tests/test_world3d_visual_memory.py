from wowbot.vision.world3d.visual_memory import World3DVisualMemory


def signature(token="same", shift=0):
    return {"version": 2, "representation_space": "WORLD3D",
            "signature_id": token,
            "shape": {"w_bin": 10+shift, "h_bin": 20, "aspect": .5},
            "appearance": {"brightness_bin": 10, "saturation_bin": 12,
                           "red_bin": 14, "green_bin": 9, "blue_bin": 8,
                           "fill_bin": 18}}


def track(track_id, token="same", identity=None):
    belief = ({"state": "CONFIRMED", "identity": identity, "confidence": .98,
               "fact": True, "evidence_refs": ["hover:1"]} if identity else
              {"state": "UNKNOWN", "identity": None, "confidence": 0., "fact": False})
    return {"track_id": track_id, "visual_signature": signature(token),
            "bearing": {"horizontal": .2, "vertical": 0.},
            "bbox": {"left": 10, "top": 20, "right": 40, "bottom": 90},
            "identity_belief": belief}


def test_visual_memory_matches_recent_signature_but_does_not_confirm_identity():
    memory = World3DVisualMemory(ttl_seconds=10)
    memory.remember_track(track("old", identity="Jaina"), now=1.)
    match = memory.reacquire_candidate(track("new"), now=3.)

    assert match["prior_track_id"] == "old"
    assert match["confirmed_identity_linkage"]["identity"] == "Jaina"
    assert match["semantic_fact"] is False
    assert "world" not in " ".join(match.keys()).lower()


def test_visual_memory_expires_and_rejects_ambiguous_matches():
    memory = World3DVisualMemory(ttl_seconds=2)
    memory.remember_track(track("old"), now=1.)
    assert memory.reacquire_candidate(track("new"), now=4.) is None

    memory.remember_track(track("a"), now=5.)
    memory.remember_track(track("b"), now=5.1)
    assert memory.reacquire_candidate(track("new"), now=5.2) is None


def test_visual_memory_is_bounded():
    memory = World3DVisualMemory(max_entries=2)
    for index in range(4):
        memory.remember_track(track(str(index), token=str(index)), now=float(index))
    assert len(memory._entries) == 2

