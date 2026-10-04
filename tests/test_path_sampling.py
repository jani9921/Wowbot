
from wowbot.navigation.path_sampling import PathTrace, sample_path


def test_trace_skips_dense_noise():
    t = PathTrace(context_id="map:1409", min_spacing=0.01)
    assert t.add(0.5, 0.5, 1.0)
    assert not t.add(0.501, 0.501, 2.0)
    assert t.add(0.52, 0.5, 3.0)
    assert len(t.samples) == 2


def test_trace_length():
    t = sample_path(
        [(0.0, 0.0, 1.0), (0.1, 0.0, 2.0), (0.1, 0.2, 3.0)],
        context_id="map:1409",
        min_spacing=0.0,
    )
    assert round(t.length, 6) == 0.3


def test_trace_context_and_edge():
    t = sample_path(
        [(0.1, 0.2, 1.0)],
        context_id="wc:exile-s-reach:map",
        edge_id="edge-1",
    )
    assert t.context_id == "wc:exile-s-reach:map"
    assert t.edge_id == "edge-1"
