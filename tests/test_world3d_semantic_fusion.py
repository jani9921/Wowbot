from wowbot.vision.world3d.semantic_fusion import SemanticEvidenceFusion


def row(field, label, confidence, source, at=1., **extra):
    return {"track_id": "WORLD3D:1", "field": field, "label": label,
            "confidence": confidence, "source": source, "observed_at": at,
            "evidence_id": f"{source}:{field}:{label}:{at}", **extra}


def test_high_reliability_mouseover_confirms_identity_in_one_frame():
    fusion = SemanticEvidenceFusion()
    result = fusion.fuse("WORLD3D:1", [
        row("identity", "Lady Jaina Proudmoore", 1., "MOUSEOVER_TELEMETRY",
            ground_truth=True),
    ], now=1.)

    assert result["identity_belief"]["state"] == "CONFIRMED"
    assert result["identity_belief"]["identity"] == "Lady Jaina Proudmoore"
    assert result["identity_belief"]["fact"] is True
    assert result["field_freshness"]["identity"] == "FRESH"


def test_low_reliability_prior_needs_temporal_repetition_and_cannot_be_fact():
    fusion = SemanticEvidenceFusion()
    hint = row("role", "QUEST_GIVER", 1., "MINIMAP_ASSOCIATION")
    first = fusion.fuse("WORLD3D:1", [hint], now=1.)
    second = fusion.fuse("WORLD3D:1", [{**hint, "observed_at": 1.1}], now=1.1)

    assert first["role_beliefs"][0]["belief"] == "CANDIDATE"
    # Reliability remains below the confirm threshold even after repetition;
    # it is a useful cross-view prior, never tooltip-grade truth.
    assert second["role_beliefs"][0]["belief"] == "CANDIDATE"
    assert second["role_beliefs"][0]["fact"] is False


def test_hysteresis_retains_then_expires_identity_by_field_policy():
    fusion = SemanticEvidenceFusion()
    evidence = row("identity", "Jaina", 1., "TOOLTIP", ground_truth=True)
    confirmed = fusion.fuse("WORLD3D:1", [evidence], now=1.)
    retained = fusion.fuse("WORLD3D:1", [], now=5.)
    expired = fusion.fuse("WORLD3D:1", [], now=20.)

    assert confirmed["identity_belief"]["state"] == "CONFIRMED"
    assert retained["identity_belief"]["identity"] == "Jaina"
    assert retained["field_freshness"]["identity"] == "FRESH"
    assert expired["identity_belief"]["state"] == "UNKNOWN"
    assert expired["field_freshness"]["identity"] == "EXPIRED"


def test_strong_tooltip_contradiction_overrides_weak_map_prior():
    fusion = SemanticEvidenceFusion()
    fusion.fuse("WORLD3D:1", [
        row("role", "QUEST_GIVER", 1., "QUEST_TELEMETRY", ground_truth=True),
    ], now=1.)
    result = fusion.fuse("WORLD3D:1", [
        row("role", "QUEST_GIVER", .9, "MINIMAP_ASSOCIATION", at=1.1),
        row("role", "VENDOR", 1., "TOOLTIP", at=1.1, ground_truth=True),
    ], now=1.1)

    confirmed = [belief for belief in result["role_beliefs"]
                 if belief["belief"] == "CONFIRMED"]
    assert confirmed and confirmed[0]["label"] == "VENDOR"

