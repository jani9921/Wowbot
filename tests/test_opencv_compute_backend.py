import cv2
import numpy as np
import pytest

from wowbot.vision.opencv_backend import OpenCvComputeBackend
from wowbot.vision.world_map_graph_vision import WorldMapGraphVision
from wowbot.vision.world_map_raster import WorldMapRasterFeatureExtractor
from wowbot.vision.world3d.models import PixelRect, WorldSceneROI
from wowbot.vision.world3d.v2 import World3DPerceptionV2
from wowbot.vision.world3d.v3 import World3DPerceptionV3


def test_cpu_backend_runs_fused_batches_and_reports_diagnostics():
    backend = OpenCvComputeBackend("CPU")
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    image[20:24, 5:55] = 180

    gray, closed, contrast = backend.raster_corridor_primitives(image)

    assert gray.shape == closed.shape == contrast.shape == image.shape[:2]
    status = backend.status()
    assert status.requested == "CPU"
    assert status.active == "CPU"
    assert status.cpu_batches == 1
    assert status.accelerated_batches == 0


def test_cuda_request_falls_back_when_opencv_has_no_enabled_cuda_device():
    class NoCuda:
        @staticmethod
        def getCudaEnabledDeviceCount():
            return 0

    class CpuOnlyOpenCv:
        cuda = NoCuda()
        cuda_GpuMat = object

    backend = OpenCvComputeBackend("CUDA", cv_module=CpuOnlyOpenCv())

    assert backend.status().active == "CPU"
    assert backend.status().reason == "no_cuda_enabled_opencv_device"


def test_auto_backend_is_always_an_explicit_cpu_or_cuda_choice():
    backend = OpenCvComputeBackend("AUTO")
    status = backend.status()
    assert status.active in {"CPU", "CUDA"}
    assert status.cuda_available is (status.cuda_device_count > 0 and status.reason == "cuda_ready")


def test_invalid_backend_mode_is_rejected_instead_of_silently_guessed():
    with pytest.raises(ValueError, match="AUTO, CPU, or CUDA"):
        OpenCvComputeBackend("VULKAN")


def test_world_map_extractors_use_the_selected_compute_backend():
    backend = OpenCvComputeBackend("CPU")
    image = np.zeros((180, 240, 3), dtype=np.uint8)
    image[:] = (120, 90, 50)
    image[80:84, 20:180] = (170, 150, 120)

    assert isinstance(WorldMapRasterFeatureExtractor(compute_backend=backend).extract(image), tuple)
    assert isinstance(WorldMapGraphVision(compute_backend=backend).extract(image), tuple)
    diagnostics = backend.diagnostics()
    assert diagnostics["active"] == "CPU"
    assert diagnostics["cpu_batches"] >= 3


def test_world3d_v2_and_fast_tracker_share_selected_compute_backend():
    backend = OpenCvComputeBackend("CPU")
    image = np.zeros((96, 128, 4), dtype=np.uint8)
    image[:, :, 3] = 255
    image[24:78, 52:76, :3] = 150
    roi = WorldSceneROI(PixelRect(0, 0, 128, 96))

    v2 = World3DPerceptionV2(compute_backend=backend)
    v2.process(image.tobytes(), 128, 96, roi)
    before = backend.status().cpu_batches
    assert before >= 1
    assert v2.last_diagnostics["opencv_compute"]["active"] == "CPU"

    v3 = World3DPerceptionV3(detector_hz=5, compute_backend=backend)
    v3.process(image.tobytes(), 128, 96, roi, observed_at=1.)
    v3.process(image.tobytes(), 128, 96, roi, observed_at=1.05)
    assert backend.status().cpu_batches > before
    assert v3.last_diagnostics["opencv_compute"]["active"] == "CPU"
