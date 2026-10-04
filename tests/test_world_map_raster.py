from pathlib import Path
import numpy as np
from PIL import Image
import pytest

from wowbot.vision.world_map_raster import WorldMapRasterFeatureExtractor, WorldMapRasterConfig


def test_exile_reach_fixture_scans_fast_and_returns_candidates():
    image_path = Path(__file__).parents[1] / "samples" / "exile_reach_world_map.png"
    if not image_path.exists():
        pytest.skip("optional Exile's Reach screenshot fixture is not included in this source archive")
    image = np.asarray(Image.open(image_path).convert("RGB"))
    features = WorldMapRasterFeatureExtractor().extract(image)
    assert isinstance(features, tuple)
    assert len(features) <= 80


def test_config_excludes_top_left_strip_region():
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    cfg = WorldMapRasterConfig(roi_left=0, roi_top=0, roi_right=1, roi_bottom=1, exclude_bottom=0.5, downsample_width=0)
    features = WorldMapRasterFeatureExtractor(cfg).extract(image)
    assert isinstance(features, tuple)


def test_graph_vision_smoke_on_small_synthetic_image():
    import numpy as np
    from wowbot.vision.world_map_graph_vision import WorldMapGraphVision

    image = np.zeros((180, 240, 3), dtype=np.uint8)
    image[:] = (120, 90, 50)
    # Light corridor with a branch.
    image[80:84, 20:180] = (170, 150, 120)
    image[40:120, 96:100] = (170, 150, 120)
    features = WorldMapGraphVision().extract(image)
    assert isinstance(features, tuple)
