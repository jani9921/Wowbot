from wowbot.navigation.path_sampling import PathSample, PathTrace
from wowbot.navigation.path_geometry import simplify_path


def test_simplify_keeps_endpoints():
    trace = PathTrace(
        context_id="map:1409",
        min_spacing=0.0,
        samples=[
            PathSample(0.0, 0.0, 1.0),
            PathSample(0.1, 0.0, 2.0),
            PathSample(0.2, 0.0, 3.0),
            PathSample(0.2, 0.1, 4.0),
        ],
    )
    geo = simplify_path(trace, min_turn_deg=15, min_vertex_spacing=0.01)
    assert geo.vertices[0].source_sample_index == 0
    assert geo.vertices[-1].source_sample_index == 3


def test_simplify_detects_turn():
    trace = PathTrace(
        context_id="map:1409",
        min_spacing=0.0,
        samples=[
            PathSample(0.0, 0.0, 1.0),
            PathSample(0.1, 0.0, 2.0),
            PathSample(0.2, 0.0, 3.0),
            PathSample(0.2, 0.1, 4.0),
            PathSample(0.2, 0.2, 5.0),
        ],
    )
    geo = simplify_path(trace, min_turn_deg=15, min_vertex_spacing=0.01)
    indices = [v.source_sample_index for v in geo.vertices]
    assert 2 in indices
