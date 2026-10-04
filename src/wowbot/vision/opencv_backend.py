"""Capability-gated OpenCV CPU/CUDA execution for vision preprocessing.

The CUDA path is optional and never an authority or a semantic shortcut.  A
normal PyPI OpenCV build commonly exposes ``cv2.cuda`` while containing no
CUDA device code; therefore module presence alone is deliberately insufficient.
Every fused operation falls back atomically to its CPU equivalent on an
unsupported primitive or runtime CUDA error.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any

import numpy as np

try:  # pragma: no cover - import failure is exercised through injection
    import cv2 as _cv2  # type: ignore
except Exception:  # pragma: no cover
    _cv2 = None


@dataclass(frozen=True, slots=True)
class OpenCvBackendStatus:
    requested: str
    active: str
    cuda_device_count: int
    cuda_available: bool
    reason: str
    accelerated_batches: int
    cpu_batches: int
    runtime_fallbacks: int
    last_fallback_reason: str | None


class OpenCvComputeBackend:
    """Run eligible OpenCV batches on CUDA and retain a lossless CPU fallback.

    ``AUTO`` is the production default.  ``CUDA`` requests acceleration but is
    intentionally non-strict: an AMD/Intel machine, a CPU-only OpenCV wheel, or
    a CUDA runtime error selects CPU and remains operational.  This class keeps
    uploads/downloads at batch boundaries instead of bouncing every primitive
    between host and device memory.
    """

    _MODES = {"AUTO", "CPU", "CUDA"}
    _REQUIRED_CUDA_APIS = (
        "cvtColor", "resize", "createGaussianFilter",
        "createBoxFilter", "createCannyEdgeDetector",
        "createMorphologyFilter", "absdiff", "split",
    )

    def __init__(self, mode: str | None = None, *, cv_module: Any = None) -> None:
        self.cv = _cv2 if cv_module is None else cv_module
        # OpenCV otherwise defaults to every logical CPU (12 on the live
        # laptop). PyTorch/Ultralytics has its own pool, so concurrent detector
        # refreshes caused severe oversubscription and 500-900 ms tracker
        # stalls. Small vision ROIs are faster and much steadier with a bounded
        # pool. This affects execution only, never perception semantics.
        try:
            cv_threads = max(1, int(os.getenv("WOWBOT_OPENCV_THREADS", "2")))
            if self.cv is not None and hasattr(self.cv, "setNumThreads"):
                self.cv.setNumThreads(cv_threads)
        except (TypeError, ValueError):
            cv_threads = 2
        self.cpu_thread_limit = cv_threads
        requested = str(mode or os.getenv("WOWBOT_OPENCV_BACKEND", "AUTO")).upper()
        if requested not in self._MODES:
            raise ValueError("WOWBOT_OPENCV_BACKEND must be AUTO, CPU, or CUDA")
        self.requested = requested
        self._accelerated_batches = 0
        self._cpu_batches = 0
        self._runtime_fallbacks = 0
        self._last_fallback_reason: str | None = None
        self.cuda_device_count, capability_reason = self._probe_cuda()
        self.cuda_available = self.cuda_device_count > 0 and capability_reason == "cuda_ready"
        if requested == "CPU":
            self.active, self.reason = "CPU", "cpu_requested"
        elif self.cuda_available:
            self.active, self.reason = "CUDA", "cuda_ready"
        else:
            self.active, self.reason = "CPU", capability_reason

    def _probe_cuda(self) -> tuple[int, str]:
        if self.cv is None:
            return 0, "opencv_unavailable"
        cuda = getattr(self.cv, "cuda", None)
        gpu_mat = getattr(self.cv, "cuda_GpuMat", None)
        if cuda is None or gpu_mat is None:
            return 0, "opencv_cuda_api_missing"
        try:
            count = int(cuda.getCudaEnabledDeviceCount())
        except Exception as exc:
            return 0, f"cuda_probe_failed:{type(exc).__name__}"
        if count <= 0:
            return 0, "no_cuda_enabled_opencv_device"
        missing = [name for name in self._REQUIRED_CUDA_APIS if not hasattr(cuda, name)]
        if missing:
            return count, "cuda_primitives_missing:" + ",".join(missing)
        return count, "cuda_ready"

    def status(self) -> OpenCvBackendStatus:
        return OpenCvBackendStatus(
            requested=self.requested,
            active=self.active,
            cuda_device_count=self.cuda_device_count,
            cuda_available=self.cuda_available,
            reason=self.reason,
            accelerated_batches=self._accelerated_batches,
            cpu_batches=self._cpu_batches,
            runtime_fallbacks=self._runtime_fallbacks,
            last_fallback_reason=self._last_fallback_reason,
        )

    def diagnostics(self) -> dict[str, Any]:
        return {**asdict(self.status()), "cpu_thread_limit": self.cpu_thread_limit}

    def resize(self, image: np.ndarray, size: tuple[int, int], *, interpolation: int) -> np.ndarray:
        if self.active == "CUDA":
            try:
                gpu = self._upload(image)
                result = self.cv.cuda.resize(gpu, size, interpolation=interpolation).download()
                self._accelerated_batches += 1
                return result
            except Exception as exc:  # hardware/build-specific; safe fallback is required
                self._record_fallback("resize", exc)
        self._cpu_batches += 1
        return self.cv.resize(image, size, interpolation=interpolation)

    def world3d_gray(self, raw_bgra: bytes, width: int, height: int,
                     downsample: int) -> np.ndarray:
        """Return the World3D luminance pyramid base as float32.

        CUDA performs conversion and nearest-neighbour reduction in one
        upload/download batch. CPU deliberately retains the historical
        strided BT.601 calculation exactly, so fallback cannot alter the
        established detector thresholds or golden replays.
        """
        step = max(1, int(downsample))
        pixels = np.frombuffer(raw_bgra, dtype=np.uint8).reshape(height, width, 4)
        if self.active == "CUDA":
            try:
                gpu = self._upload(pixels)
                gray = self.cv.cuda.cvtColor(gpu, self.cv.COLOR_BGRA2GRAY)
                out_w = max(1, (width + step - 1) // step)
                out_h = max(1, (height + step - 1) // step)
                reduced = self.cv.cuda.resize(
                    gray, (out_w, out_h), interpolation=self.cv.INTER_NEAREST)
                self._accelerated_batches += 1
                return reduced.download().astype(np.float32, copy=False)
            except Exception as exc:
                self._record_fallback("world3d_gray", exc)
        self._cpu_batches += 1
        sample = pixels[::step, ::step, :3].astype(np.float32)
        return .114 * sample[:, :, 0] + .587 * sample[:, :, 1] + .299 * sample[:, :, 2]

    def raster_corridor_primitives(self, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return gray, closed-edge and local-contrast images as one batch."""
        if self.active == "CUDA":
            try:
                gpu = self._upload(rgb)
                gray = self.cv.cuda.cvtColor(gpu, self.cv.COLOR_RGB2GRAY)
                canny = self.cv.cuda.createCannyEdgeDetector(45., 115., 3, True)
                edges = canny.detect(gray)
                kernel = self.cv.getStructuringElement(self.cv.MORPH_ELLIPSE, (3, 3))
                morph = self.cv.cuda.createMorphologyFilter(
                    self.cv.MORPH_CLOSE, edges.type(), kernel)
                closed = morph.apply(edges)
                mean_filter = self.cv.cuda.createBoxFilter(gray.type(), gray.type(), (9, 9))
                local_mean = mean_filter.apply(gray)
                contrast = self.cv.cuda.absdiff(gray, local_mean)
                result = gray.download(), closed.download(), contrast.download()
                self._accelerated_batches += 1
                return result
            except Exception as exc:
                self._record_fallback("raster_corridor_primitives", exc)
        self._cpu_batches += 1
        gray = self.cv.cvtColor(rgb, self.cv.COLOR_RGB2GRAY)
        edges = self.cv.Canny(gray, 45, 115, L2gradient=True)
        kernel = self.cv.getStructuringElement(self.cv.MORPH_ELLIPSE, (3, 3))
        closed = self.cv.morphologyEx(edges, self.cv.MORPH_CLOSE, kernel, iterations=1)
        local_mean = self.cv.blur(gray, (9, 9))
        return gray, closed, self.cv.absdiff(gray, local_mean)

    def graph_line_primitives(
        self, rgb: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Return gray, H/S/V, edges and local contrast with one GPU upload."""
        if self.active == "CUDA":
            try:
                gpu = self._upload(rgb)
                gray = self.cv.cuda.cvtColor(gpu, self.cv.COLOR_RGB2GRAY)
                hsv = self.cv.cuda.cvtColor(gpu, self.cv.COLOR_RGB2HSV)
                h, s, v = self.cv.cuda.split(hsv)
                fine = self.cv.cuda.createGaussianFilter(gray.type(), gray.type(), (5, 5), 1.0)
                broad = self.cv.cuda.createGaussianFilter(gray.type(), gray.type(), (37, 37), 6.0)
                blur = fine.apply(gray)
                local = broad.apply(gray)
                edges = self.cv.cuda.createCannyEdgeDetector(38., 105., 3, True).detect(blur)
                contrast = self.cv.cuda.absdiff(gray, local)
                result = tuple(item.download() for item in (gray, h, s, v, edges, contrast))
                self._accelerated_batches += 1
                return result  # type: ignore[return-value]
            except Exception as exc:
                self._record_fallback("graph_line_primitives", exc)
        self._cpu_batches += 1
        gray = self.cv.cvtColor(rgb, self.cv.COLOR_RGB2GRAY)
        hsv = self.cv.cvtColor(rgb, self.cv.COLOR_RGB2HSV)
        h, s, v = self.cv.split(hsv)
        blur = self.cv.GaussianBlur(gray, (0, 0), 1.0)
        edges = self.cv.Canny(blur, 38, 105, L2gradient=True)
        local = self.cv.GaussianBlur(gray, (0, 0), 6.0)
        return gray, h, s, v, edges, self.cv.absdiff(gray, local)

    def morphology_close(self, mask: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        if self.active == "CUDA":
            try:
                gpu = self._upload(mask)
                morph = self.cv.cuda.createMorphologyFilter(
                    self.cv.MORPH_CLOSE, gpu.type(), kernel)
                result = morph.apply(gpu).download()
                self._accelerated_batches += 1
                return result
            except Exception as exc:
                self._record_fallback("morphology_close", exc)
        self._cpu_batches += 1
        return self.cv.morphologyEx(mask, self.cv.MORPH_CLOSE, kernel, iterations=1)

    def _upload(self, image: np.ndarray):
        gpu = self.cv.cuda_GpuMat()
        gpu.upload(np.ascontiguousarray(image))
        return gpu

    def _record_fallback(self, operation: str, exc: Exception) -> None:
        self._runtime_fallbacks += 1
        self._last_fallback_reason = f"{operation}:{type(exc).__name__}:{exc}"


def create_opencv_backend(mode: str | None = None) -> OpenCvComputeBackend | None:
    """Return a usable backend, or ``None`` when OpenCV is not installed."""
    if _cv2 is None:
        return None
    return OpenCvComputeBackend(mode)
