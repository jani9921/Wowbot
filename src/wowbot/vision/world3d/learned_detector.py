"""Optional learned World3D detector adapter.

Learned output is deliberately only *visual evidence*.  Even when a model was
trained with a convenient annotation name such as ``npc_body``, this adapter
publishes an UNKNOWN subject proposal.  Identity, role and hostility still
require temporal/fused evidence (for example addon-confirmed mouseover).

The small backend protocol keeps World3D independent from Ultralytics/YOLO.
Tests and future ONNX/TensorRT backends can implement the same ``predict``
contract without changing the perception pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
from typing import Any, Protocol, Sequence

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover - installed package path
    from adapters.numpy_runtime import np

from .models import PixelRect, WorldCandidate, WorldSceneROI


@dataclass(frozen=True, slots=True)
class LearnedDetection:
    """One crop-relative detector result with no asserted game semantics."""

    label: str
    confidence: float
    left: float
    top: float
    right: float
    bottom: float


class LearnedDetectorBackend(Protocol):
    """Model-neutral inference boundary required by the World3D spec."""

    name: str

    def predict(self, bgr_roi: Any, *, confidence: float,
                iou: float) -> Sequence[LearnedDetection]: ...


class UltralyticsYoloBackend:
    """Lazy optional Ultralytics backend; importing wowbot never requires it."""

    name = "ultralytics_yolo"

    def __init__(self, model_path: str | Path, *, device: str | int | None = None,
                 image_size: int = 640, max_detections: int = 20,
                 warmup_in_background: bool = False) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(self.model_path)
        self.device = device
        self.image_size = max(320, int(image_size))
        self.max_detections = max(1, int(max_detections))
        self.model = None
        self.status = "warming" if warmup_in_background else "loading"
        self.load_error: str | None = None
        self.active_device: str | None = None
        self._lock = threading.Lock()
        if warmup_in_background:
            threading.Thread(target=self._load_and_warmup,
                             name="aipc-yolo-warmup", daemon=True).start()
        else:
            self._load(warmup=False)
            if self.status == "error":
                raise RuntimeError(self.load_error or "YOLO model did not initialize")

    def _load(self, *, warmup: bool) -> None:
        try:
            from ultralytics import YOLO  # type: ignore[import-not-found]
            if self.device == "auto":
                try:
                    import torch
                    self.device = 0 if torch.cuda.is_available() else "cpu"
                except ImportError:
                    self.device = "cpu"
            # CUDA inference still performs preprocessing and NMS on CPU.
            # Leaving PyTorch at all available logical CPUs made its pool race
            # OpenCV, the GUI and WoW, producing periodic 500+ ms stalls even
            # though median inference was fast. Reserve cores for the live
            # tracker; these limits are configurable for larger desktops.
            try:
                import torch
                torch.set_num_threads(max(1, int(os.getenv("AIPC_TORCH_THREADS", "2"))))
                try:
                    torch.set_num_interop_threads(max(
                        1, int(os.getenv("AIPC_TORCH_INTEROP_THREADS", "1"))))
                except RuntimeError:
                    # PyTorch permits this setting only before its first
                    # parallel operation. A previous optional consumer may
                    # already have initialized it; inference remains valid.
                    pass
                if torch.cuda.is_available() and self.device != "cpu":
                    # Client windows can change aspect/shape. cuDNN benchmark
                    # re-runs an expensive algorithm search for every unseen
                    # tensor shape (18 s observed on the RTX 2050), which is
                    # disastrous for live latency. Deterministic selection is
                    # slightly less aggressive but bounded.
                    torch.backends.cudnn.benchmark = False
            except (ImportError, TypeError, ValueError):
                pass
            if Path(self.model_path).suffix.lower() == ".onnx":
                from .directml import enable_directml_for_onnx
                if enable_directml_for_onnx():
                    # Ultralytics then requests the CPU provider; the adapter
                    # puts DirectML first.  Pre/post-processing stays on CPU.
                    self.device = "cpu"
            model = YOLO(str(self.model_path))
            if warmup:
                # CUDA kernels and model graph are initialized outside the
                # capture/perception worker. Until this is done predict()
                # returns no learned evidence; cheap CV remains operational.
                dummy = np.zeros((self.image_size, self.image_size, 3), dtype=np.uint8)
                kwargs: dict[str, Any] = {
                    "verbose": False, "conf": .9, "iou": .45,
                    "imgsz": self.image_size, "max_det": 1,
                    # The production TensorRT engine is a static square graph.
                    # Always square-letterbox inputs so window aspect-ratio
                    # changes never select an unsupported tensor shape.
                    "rect": False,
                }
                if self.device is not None:
                    kwargs["device"] = self.device
                model(dummy, **kwargs)
            try:
                # Ultralytics keeps the original checkpoint module on CPU and
                # owns the inference copy under predictor. Reading
                # model.model.parameters() therefore falsely reported CPU even
                # while CUDA inference was active.
                active_device = str(model.predictor.device)
            except (AttributeError, StopIteration, TypeError):
                active_device = str(self.device) if self.device is not None else "auto"
            if Path(self.model_path).suffix.lower() == ".onnx":
                from . import directml
                if directml._ENABLED:
                    active_device = "directml"
            with self._lock:
                self.model = model
                self.active_device = active_device
                self.status = "ready"
        except Exception as exc:  # surfaced in diagnostics and on explicit use
            with self._lock:
                self.load_error = f"{type(exc).__name__}:{exc}"
                self.status = "error"

    def _load_and_warmup(self) -> None:
        self._load(warmup=True)

    def predict(self, bgr_roi: Any, *, confidence: float,
                iou: float) -> Sequence[LearnedDetection]:
        with self._lock:
            status, model, load_error = self.status, self.model, self.load_error
        if status in {"warming", "loading"} or model is None and status != "error":
            return ()
        if status == "error" or model is None:
            raise RuntimeError(load_error or "YOLO model did not initialize")
        kwargs: dict[str, Any] = {
            "verbose": False,
            "conf": float(confidence),
            "iou": float(iou),
            "imgsz": self.image_size,
            "max_det": self.max_detections,
            "rect": False,
        }
        if self.device is not None:
            kwargs["device"] = self.device
        # One perception worker owns inference, but the lock also guarantees
        # no overlap with publication at the end of asynchronous warm-up.
        with self._lock:
            result = model(bgr_roi, **kwargs)[0]
            try:
                self.active_device = str(model.predictor.device)
            except (AttributeError, TypeError):
                pass
        names = result.names or {}
        output: list[LearnedDetection] = []
        for box in (() if result.boxes is None else result.boxes):
            class_id = int(box.cls[0].item())
            score = float(box.conf[0].item())
            left, top, right, bottom = (float(value) for value in box.xyxy[0].tolist())
            label = str(names.get(class_id, class_id) if isinstance(names, dict)
                        else names[class_id])
            output.append(LearnedDetection(label, score, left, top, right, bottom))
        return output


_SYMBOL_LABELS = frozenset({
    "quest_marker", "symbol", "overhead_symbol", "overhead_symbol_like",
})
_OBJECT_LABELS = frozenset({
    "object", "game_object", "quest_object", "resource_node",
    "world_object_like", "quest_object_outline_like",
})
_SCENE_LABELS = frozenset({
    "scene_mass", "door", "cave_entrance", "obstacle",
    "entrance_or_door_like",
})
_CORPSE_LABELS = frozenset({"corpse", "dead_body", "loot_body", "corpse_like"})
_INTERACT_SYMBOL_LABELS = frozenset({"interact_icon", "interaction_icon", "soft_target_icon"})
_INTERACT_OBJECT_LABELS = frozenset({"interactable_object", "interaction_highlight"})


def _visual_family(label: str) -> tuple[str, tuple[str, ...]]:
    """Map a training taxonomy to UNKNOWN-first appearance families."""
    normalized = label.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in _INTERACT_SYMBOL_LABELS:
        return "unknown_symbol_candidate", ("learned_symbol_like", "interact_cue_like")
    if normalized in _CORPSE_LABELS:
        return "unknown_subject_candidate", ("learned_subject_like", "learned_corpse_like")
    if normalized in _INTERACT_OBJECT_LABELS:
        return "unknown_object_candidate", ("learned_object_like", "learned_interactable_like")
    if normalized in _SYMBOL_LABELS:
        return "unknown_symbol_candidate", ("learned_symbol_like",)
    if normalized in _OBJECT_LABELS:
        labels = ["learned_object_like"]
        if normalized in {"quest_object", "quest_object_outline_like"}:
            labels.extend(("quest_object_like", "outline_like_cue"))
        return "unknown_object_candidate", tuple(labels)
    if normalized in _SCENE_LABELS:
        return "unknown_scene_candidate", ("learned_scene_geometry_like",)
    # npc, mob, hostile_unit, player, corpse and unknown unit labels all stay
    # UNKNOWN until evidence fusion confirms their semantics.
    return "unknown_subject_candidate", ("learned_subject_like",)


def _intersects(a: PixelRect, b: PixelRect) -> bool:
    return not (a.right <= b.left or a.left >= b.right or
            a.bottom <= b.top or a.top >= b.bottom)


def _overlap_fraction(a: PixelRect, b: PixelRect) -> float:
    width = max(0, min(a.right, b.right) - max(a.left, b.left))
    height = max(0, min(a.bottom, b.bottom) - max(a.top, b.top))
    area = a.width * a.height
    return (width * height) / area if area else 0.0


class LearnedWorldDetector:
    """Adapter from a learned backend to canonical UNKNOWN WorldCandidates."""

    def __init__(self, backend: LearnedDetectorBackend, *, confidence: float = .30,
                 iou: float = .45, max_detections: int = 24,
                 label_thresholds: dict[str, float] | None = None,
                 per_label_limits: dict[str, int] | None = None,
                 adaptive_sampling: bool = True,
                 full_scan_interval: int = 3,
                 full_scan_image_size: int = 512,
                 foveal_image_size: int = 640) -> None:
        self.backend = backend
        self.confidence = max(0., min(1., float(confidence)))
        self.iou = max(0., min(1., float(iou)))
        self.max_detections = max(1, int(max_detections))
        self.label_thresholds = {
            str(label).strip().lower().replace("-", "_").replace(" ", "_"):
                max(0., min(1., float(value)))
            for label, value in (label_thresholds or {}).items()
        }
        self.per_label_limits = {
            str(label).strip().lower().replace("-", "_").replace(" ", "_"):
                max(0, int(value))
            for label, value in (per_label_limits or {}).items()
        }
        self.adaptive_sampling = bool(adaptive_sampling)
        self.full_scan_interval = max(2, int(full_scan_interval))
        self.full_scan_image_size = max(320, int(full_scan_image_size))
        self.foveal_image_size = max(320, int(foveal_image_size))
        self._scan_index = 0
        self._last_focus: PixelRect | None = None
        self.last_diagnostics: dict[str, object] = {
            "backend": getattr(backend, "name", type(backend).__name__),
            "status": getattr(backend, "status", "ready"),
        }

    def detect(self, raw: bytes, width: int, height: int,
               scene: WorldSceneROI) -> tuple[WorldCandidate, ...]:
        if width < 1 or height < 1 or len(raw) != width * height * 4:
            raise ValueError("learned detector requires one complete BGRA frame")
        # Heuristic CV deliberately starts below the top HUD band. Learned
        # inference uses its own taller ROI so distant overhead markers are
        # not physically cropped before YOLO sees them.
        roi = scene.learned_rect or scene.rect
        self._scan_index += 1
        use_fovea = bool(
            self.adaptive_sampling and self._last_focus is not None
            and self._scan_index % self.full_scan_interval != 0)
        inference_roi = self._foveal_roi(roi, self._last_focus) if use_fovea else roi
        scan_mode = "FOVEAL" if use_fovea else "FULL"
        requested_image_size = (
            self.foveal_image_size if use_fovea else self.full_scan_image_size)
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        crop = pixels[inference_roi.top:inference_roi.bottom,
                      inference_roi.left:inference_roi.right, :3]
        masked_hard_ui_regions = 0
        if scene.hard_excluded_rects:
            # Remove opaque UI islands from the detector input itself so they
            # cannot consume detections or influence learned attention.
            crop = crop.copy()
            for excluded in scene.hard_excluded_rects:
                left = max(inference_roi.left, excluded.left)
                top = max(inference_roi.top, excluded.top)
                right = min(inference_roi.right, excluded.right)
                bottom = min(inference_roi.bottom, excluded.bottom)
                if right <= left or bottom <= top:
                    continue
                crop[top-inference_roi.top:bottom-inference_roi.top,
                     left-inference_roi.left:right-inference_roi.left] = 0
                masked_hard_ui_regions += 1
        adaptive_predict = getattr(self.backend, "predict_at_size", None)
        if callable(adaptive_predict):
            detections = adaptive_predict(
                crop, confidence=self.confidence, iou=self.iou,
                image_size=requested_image_size)
        else:
            detections = self.backend.predict(
                crop, confidence=self.confidence, iou=self.iou)
        candidates: list[WorldCandidate] = []
        rejected = 0
        rejected_by_threshold = 0
        rejected_by_limit = 0
        rejected_by_ui_exclusion = 0
        self_avatar_overlap_candidates = 0
        label_counts: dict[str, int] = {}
        # Apply the label budgets to the strongest boxes first. This prevents
        # a cloud of weaker same-class proposals from consuming the complete
        # runtime attention budget.
        ordered = sorted(detections, key=lambda item: float(item.confidence), reverse=True)
        for detection in ordered:
            score = max(0., min(1., float(detection.confidence)))
            normalized_label = detection.label.strip().lower().replace("-", "_").replace(" ", "_")
            threshold = self.label_thresholds.get(normalized_label, self.confidence)
            if score < threshold:
                rejected += 1
                rejected_by_threshold += 1
                continue
            limit = self.per_label_limits.get(normalized_label)
            if limit is not None and label_counts.get(normalized_label, 0) >= limit:
                rejected += 1
                rejected_by_limit += 1
                continue
            rect = PixelRect(
                max(roi.left, min(roi.right, inference_roi.left + round(detection.left))),
                max(roi.top, min(roi.bottom, inference_roi.top + round(detection.top))),
                max(roi.left, min(roi.right, inference_roi.left + round(detection.right))),
                max(roi.top, min(roi.bottom, inference_roi.top + round(detection.bottom))),
            )
            kind, candidate_labels = _visual_family(detection.label)
            # Broad HUD exclusion rectangles are useful for heuristic color/
            # edge proposals, but WoW renders real units *behind* translucent
            # quest-tracker and nameplate UI. Rejecting any intersection made
            # a high-confidence creature on the right side disappear at
            # runtime even though the same model found it in replay. Subject
            # classes were trained with UI hard negatives and may cross these
            # overlays; non-subject learned cues retain the conservative mask.
            # The self-avatar rectangle is not a HUD exclusion. A unit standing
            # directly in front of the player can project into the same fixed
            # screen region, so region overlap alone must never delete a learned
            # subject or overhead cue. Keep the overlap as appearance evidence;
            # identity/temporal evidence may later decide that a track is self.
            ui_exclusions = tuple(
                excluded for excluded in scene.excluded_rects
                if scene.self_avatar_rect is None or excluded != scene.self_avatar_rect)
            # Learned subjects *and learned overhead symbols* may be genuine
            # World3D content rendered behind an optional HUD location.  The
            # live 2026-09-26 frame had no minimap visible, yet Jaina's real
            # overhead marker occupied the fixed minimap rectangle and was
            # discarded here after the model detected it.  Keep these learned
            # hypotheses; temporal grouping/evidence handles false positives.
            center_x = (rect.left + rect.right) / 2
            center_y = (rect.top + rect.bottom) / 2
            hard_excluded_overlap = any(
                (_overlap_fraction(rect, excluded) >= .50
                 or (excluded.left <= center_x <= excluded.right
                     and excluded.top <= center_y <= excluded.bottom))
                for excluded in scene.hard_excluded_rects)
            excluded_overlap = (hard_excluded_overlap or (
                kind not in {"unknown_subject_candidate", "unknown_symbol_candidate"}
                and any(_intersects(rect, excluded) for excluded in ui_exclusions)))
            self_avatar_overlap_fraction = (
                _overlap_fraction(rect, scene.self_avatar_rect)
                if scene.self_avatar_rect is not None else 0.)
            if self_avatar_overlap_fraction >= .60:
                self_avatar_overlap_candidates += 1
            if rect.width < 3 or rect.height < 3 or excluded_overlap:
                rejected += 1
                if excluded_overlap:
                    rejected_by_ui_exclusion += 1
                continue
            candidates.append(WorldCandidate(
                kind=kind,
                rect=rect,
                confidence=score,
                evidence=(f"learned visual proposal: backend={self.backend.name}; "
                          f"label={detection.label}; confidence={score:.3f}"),
                appearance={
                    "source_detector": self.backend.name,
                    "learned_label_hypothesis": detection.label,
                    "learned_confidence": round(score, 4),
                    "semantic_status": "UNCONFIRMED",
                    "proposal_semantics": "UNKNOWN",
                    "self_avatar_region_overlap": round(self_avatar_overlap_fraction, 4),
                    "possible_self_avatar_overlap": self_avatar_overlap_fraction >= .60,
                },
                candidate_labels=candidate_labels,
            ))
            label_counts[normalized_label] = label_counts.get(normalized_label, 0) + 1
        candidates.sort(key=lambda candidate: candidate.confidence, reverse=True)
        output = tuple(candidates[:self.max_detections])
        if output:
            self._last_focus = max(output, key=self._focus_score).rect
        elif use_fovea:
            # A failed close look must trigger immediate global reacquisition,
            # not keep an empty tunnel-vision crop for two more refreshes.
            self._last_focus = None
        self.last_diagnostics = {
            "backend": getattr(self.backend, "name", type(self.backend).__name__),
            "status": getattr(self.backend, "status", "ready"),
            "raw_detections": len(detections),
            "rejected": rejected,
            "rejected_by_threshold": rejected_by_threshold,
            "rejected_by_label_limit": rejected_by_limit,
            "rejected_by_ui_exclusion": rejected_by_ui_exclusion,
            # Compatibility field retained for existing diagnostics consumers.
            # Fixed screen geometry is no longer sufficient for hard rejection.
            "rejected_as_self_avatar": 0,
            "self_avatar_overlap_candidates": self_avatar_overlap_candidates,
            "output_candidates": len(output),
            "label_counts": dict(label_counts),
            "semantic_contract": "UNKNOWN_FIRST",
            "sampling_mode": scan_mode,
            "masked_hard_ui_regions": masked_hard_ui_regions,
            "requested_image_size": requested_image_size,
            "inference_roi": {
                "left": inference_roi.left, "top": inference_roi.top,
                "right": inference_roi.right, "bottom": inference_roi.bottom,
            },
            "full_scan_interval": self.full_scan_interval,
        }
        active_device = getattr(self.backend, "active_device", None)
        if active_device is not None:
            self.last_diagnostics["device"] = active_device
        model_path = getattr(self.backend, "model_path", None)
        if model_path is not None:
            self.last_diagnostics["model_path"] = str(model_path)
        load_error = getattr(self.backend, "load_error", None)
        if load_error:
            self.last_diagnostics["load_error"] = load_error
        transport = getattr(self.backend, "transport", None)
        if transport:
            self.last_diagnostics["transport"] = transport
        active_image_size = getattr(self.backend, "last_image_size", None)
        if active_image_size:
            self.last_diagnostics["active_image_size"] = active_image_size
        return output

    @staticmethod
    def _focus_score(candidate: WorldCandidate) -> float:
        labels = set(candidate.candidate_labels)
        priority = (4.0 if "learned_symbol_like" in labels else
                    3.0 if "learned_subject_like" in labels else
                    2.0 if "quest_object_like" in labels else 1.0)
        return priority + float(candidate.confidence)

    @staticmethod
    def _foveal_roi(scene: PixelRect, focus: PixelRect | None) -> PixelRect:
        if focus is None:
            return scene
        center_x = (focus.left + focus.right) / 2
        center_y = (focus.top + focus.bottom) / 2
        # Preserve surrounding symbol/body context while magnifying the area
        # enough for small distant cues. Never sample less than ~38% of the
        # World3D scene in either dimension.
        crop_width = min(scene.width, max(scene.width * .38, focus.width * 3.2, 160.))
        crop_height = min(scene.height, max(scene.height * .38, focus.height * 3.2, 160.))
        left = max(scene.left, min(scene.right - crop_width, center_x - crop_width / 2))
        top = max(scene.top, min(scene.bottom - crop_height, center_y - crop_height / 2))
        return PixelRect(round(left), round(top), round(left + crop_width), round(top + crop_height))

    def close(self) -> None:
        close = getattr(self.backend, "close", None)
        if callable(close):
            close()


# 3-class unit model (creature_unit_like / quest_object_outline_like /
# overhead_symbol_like); humanoid, creature and corpse are one visual class.
# v10 epoch 65 (user 2026-10-03): best creature recall on the re-reviewed
# 3997-frame set.  Rollback: AIPC_WORLD3D_MODEL=<models>/world3d_units_3class_v8.engine
RUNTIME_MODEL_NAME = "world3d_units_3class_v10_e65.pt"
RUNTIME_ENGINE_NAME = "world3d_units_3class_v10_e65.engine"
RUNTIME_ONNX_NAME = "world3d_units_3class_v10_e65.onnx"


def _cuda_available() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False
RUNTIME_SUBJECT_CONFIDENCE = .15


def default_runtime_model_path() -> Path:
    """Prefer the optimized local TensorRT engine, retaining the PT fallback.

    TensorRT engines are GPU/driver specific and therefore optional runtime
    artifacts.  An explicit ``AIPC_WORLD3D_MODEL`` always wins.  Otherwise the
    engine built for this machine is selected when present and the portable
    PyTorch checkpoint remains the deterministic fallback.
    """
    configured = os.environ.get("AIPC_WORLD3D_MODEL", "").strip()
    if configured:
        return Path(configured).expanduser()
    models = Path(__file__).resolve().parents[4] / "models"
    engine = models / RUNTIME_ENGINE_NAME
    if engine.is_file() and _cuda_available():
        return engine
    # User 2026-10-03: AMD/Intel GPUs have no CUDA/TensorRT; DirectML runs
    # the ONNX export on any DX12 GPU.  Without either, the .pt runs on CPU.
    from .directml import directml_available
    onnx = models / RUNTIME_ONNX_NAME
    if onnx.is_file() and not _cuda_available() and directml_available():
        return onnx
    return models / RUNTIME_MODEL_NAME


def build_runtime_learned_detector(model_path: str | Path | None, *,
                                   capture_handle=None) -> LearnedWorldDetector | None:
    """Build the conservative production adapter for an explicitly selected model.

    The annotation preview deliberately uses a low threshold to maximize recall.
    Runtime has the opposite cost model: every box can become tracking and active
    perception work, so only the strongest few UNKNOWN proposals are admitted.
    """
    if model_path is None:
        return None
    path = Path(model_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"World3D model not found: {path}")
    requested_device = os.environ.get("AIPC_WORLD3D_MODEL_DEVICE", "auto").strip().lower()
    if requested_device in {"", "auto"}:
        # Resolve this sentinel in the background load worker. Ultralytics'
        # implicit default is CPU, so omitting the device would silently leave
        # an available NVIDIA GPU unused.
        device: str | int | None = "auto"
    elif requested_device.isdigit():
        device = int(requested_device)
    else:
        device = requested_device
    backend_arguments = {
        "device": device,
        "image_size": int(os.environ.get("AIPC_WORLD3D_MODEL_IMGSZ", "640")),
        "max_detections": int(os.environ.get("AIPC_WORLD3D_MODEL_RAW_MAX", "18")),
    }
    detector_kwargs = runtime_detector_kwargs()
    alternate = None
    if path.suffix.lower() == ".engine":
        candidate = path.with_name(f"{path.stem}_512.engine")
        if candidate.is_file():
            alternate = candidate
    fallback = path.with_name(RUNTIME_MODEL_NAME) if path.suffix.lower() == ".engine" else None
    capture_feed_enabled = os.environ.get("AIPC_YOLO_CAPTURE_FEED", "1").strip().lower() not in {
        "0", "false", "no", "off"}
    if capture_handle is not None and capture_feed_enabled:
        # Detector pulls the newest captured frame itself; World3D only takes
        # finished results (see capture_yolo_feed).  No frame submission path.
        from .capture_yolo_feed import CaptureDrivenYoloFeed
        client = capture_handle.client
        # Association runs on every feed result.  Alternating FULL/FOVEAL
        # crops return different object sets (outside-fovea units vanish,
        # fovea-only distant units appear), so tracks needing consecutive
        # confirmation never confirm and get new ids even with a still camera
        # (live + offline 2026-09-30).  The feed therefore scans the full
        # learned ROI on every frame unless explicitly re-enabled.
        detector_kwargs["adaptive_sampling"] = os.environ.get(
            "AIPC_YOLO_FEED_ADAPTIVE_SAMPLING", "0").strip().lower() in {
                "1", "true", "yes", "on"}
        return CaptureDrivenYoloFeed(
            model_config={
                "model_path": str(path), "device": device,
                "image_size": backend_arguments["image_size"],
                "max_detections": backend_arguments["max_detections"],
                "alternate_model_path": str(alternate) if alternate else None,
                "alternate_image_size": 512,
                "fallback_model_path": str(fallback) if fallback and fallback.is_file() else None,
            },
            detector_kwargs=detector_kwargs,
            capture_ring=client.ring_name,
            frame_lookup=client.frame_for_id,
            max_hz=float(os.environ.get("AIPC_YOLO_MAX_HZ", "30")))
    if os.environ.get("AIPC_YOLO_PROCESS", "1").strip().lower() not in {
            "0", "false", "no", "off"}:
        from .process_yolo_backend import ProcessYoloBackend
        backend = ProcessYoloBackend(
            path, **backend_arguments,
            alternate_model_path=alternate, alternate_image_size=512,
            fallback_model_path=(path.with_name(RUNTIME_MODEL_NAME)
                                 if path.suffix.lower() == ".engine" else None),
            timeout_seconds=float(os.environ.get("AIPC_YOLO_TIMEOUT_SECONDS", "30")))
    else:
        backend = UltralyticsYoloBackend(
            path, **backend_arguments, warmup_in_background=True)
    return LearnedWorldDetector(backend, **detector_kwargs)


def runtime_detector_kwargs() -> dict:
    """Production detector policy, shared by the in-process and feed paths."""
    return dict(
        # Backend threshold stays below all production class gates so runtime
        # diagnostics can distinguish model output from policy rejection.
        # Keep the backend gate recall-oriented. Class-specific admission and
        # temporal tracking below decide whether a weak visual hypothesis is
        # useful; discarding it here made live 0.08--0.19 detections invisible
        # even though the same model exposed them during offline review.
        # In the exact runtime World3D crop the concrete Jaina marker in live
        # capture 0068 scored 0.017.  Retain the existing conservative raw gate;
        # its previous loss was caused by the fixed HUD exclusion, not score.
        confidence=float(os.environ.get("AIPC_WORLD3D_MODEL_CONFIDENCE", ".01")),
        iou=float(os.environ.get("AIPC_WORLD3D_MODEL_IOU", ".45")),
        max_detections=int(os.environ.get("AIPC_WORLD3D_MODEL_MAX_DETECTIONS", "10")),
        label_thresholds={
            "humanoid_unit_like": RUNTIME_SUBJECT_CONFIDENCE,
            "creature_unit_like": RUNTIME_SUBJECT_CONFIDENCE,
            "corpse_like": .18,
            "quest_object_outline_like": .12,
            "overhead_symbol_like": float(os.environ.get(
                "AIPC_WORLD3D_OVERHEAD_CONFIDENCE", ".01")),
            # These two classes have too little verified data in v1. They stay
            # available as weak visual evidence, but require a strong score.
            "world_object_like": .25,
            "entrance_or_door_like": .35,
        },
        per_label_limits={
            "humanoid_unit_like": 4,
            # The unit model merges humanoid, creature and corpse into this
            # one class, so it keeps the former combined subject capacity.
            "creature_unit_like": 8,
            "corpse_like": 2,
            "quest_object_outline_like": 2,
            "overhead_symbol_like": 3,
            "world_object_like": 1,
            "entrance_or_door_like": 1,
        },
        adaptive_sampling=os.environ.get(
            "AIPC_WORLD3D_ADAPTIVE_SAMPLING", "1").strip().lower()
            not in {"0", "false", "no", "off"},
        full_scan_interval=int(os.environ.get(
            "AIPC_WORLD3D_FULL_SCAN_INTERVAL", "3")),
        full_scan_image_size=int(os.environ.get(
            "AIPC_WORLD3D_FULL_SCAN_IMGSZ", "640")),
        foveal_image_size=int(os.environ.get(
            "AIPC_WORLD3D_FOVEAL_IMGSZ", "640")),
    )
