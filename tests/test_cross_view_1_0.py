from wowbot.agent.cross_view import CrossViewAssociator, CrossViewResolver


def test_cross_view_requires_shared_memory_candidate_and_never_invents_transform():
    tracks = [{"track_id": "w", "source": "WORLD3D"},
              {"track_id": "m", "source": "MINIMAP_CV"},
              {"track_id": "x", "source": "WORLD_MAP_CV"}]
    recognition = [
        {"track_id": "w", "entity_candidates": [{"identity_key": "npc:1", "reliability": .8}]},
        {"track_id": "m", "entity_candidates": [{"identity_key": "npc:1", "reliability": .7}]},
        {"track_id": "x", "entity_candidates": [{"identity_key": "npc:2", "reliability": .9}]}]
    result = CrossViewAssociator().associate(tracks, recognition, 1.)
    assert len(result) == 1
    assert {result[0]["left_track_id"], result[0]["right_track_id"]} == {"w", "m"}
    assert result[0]["belief"] == "CANDIDATE"
    assert result[0]["semantic_type"] == "UNKNOWN"
    assert result[0]["coordinate_transform_used"] is False


def test_cross_view_does_not_link_appearance_or_color_alone():
    tracks = [{"track_id": "w", "source": "WORLD3D", "appearance": {"hue": "yellow"}},
              {"track_id": "m", "source": "MINIMAP_CV", "appearance": {"hue": "yellow"}}]
    assert CrossViewAssociator().associate(tracks, [], 1.) == []


def test_cross_view_resolver_exposes_surface_specific_associations_and_best_identity():
    tracks = [{"track_id": "map", "source": "WORLD_MAP_CV"},
              {"track_id": "mini", "source": "MINIMAP_CV"},
              {"track_id": "world", "source": "WORLD3D"}]
    recognition = [{"track_id": track["track_id"],
                    "entity_candidates": [{"identity_key": "npc:7", "reliability": .8}]}
                   for track in tracks]
    resolver = CrossViewResolver()
    assert len(resolver.associate_map_to_minimap(tracks, recognition, 2.)) == 1
    world = resolver.associate_minimap_to_world3d(tracks, recognition, 2.)
    assert len(world) == 1
    assert resolver.get_best_entity_identity(world)["identity_key"] == "npc:7"


def test_cross_view_conflicts_are_evidence_not_silent_identity_choice():
    hypotheses = [
        {"left_track_id": "w", "right_track_id": "m1", "entity_candidate": "npc:1",
         "belief": "CANDIDATE", "confidence": .8, "evidence": []},
        {"left_track_id": "w", "right_track_id": "m2", "entity_candidate": "npc:2",
         "belief": "CANDIDATE", "confidence": .9, "evidence": []},
    ]
    resolved = CrossViewResolver.resolve_conflicts(hypotheses)
    assert all(item["belief"] == "CONTRADICTED" for item in resolved)
    assert CrossViewResolver.get_best_entity_identity(resolved) is None


def test_exact_addon_target_guid_confirms_only_matching_entity():
    result = CrossViewResolver.associate_target_to_entity(
        {"guid": "Creature-1"}, [{"guid": "Creature-2"}, {"guid": "Creature-1", "name": "Jaina"}])
    assert result["belief"] == "CONFIRMED"
    assert result["entity"]["name"] == "Jaina"
