"""Stateful, UNKNOWN-first World3D proposal generation.

This module deliberately produces visual proposals and evidence, never entity
roles.  It complements the inexpensive legacy colour/component detector with
camera-compensated motion and generic contrast/edge/geometry proposals.
"""
from __future__ import annotations

from dataclasses import replace
import math

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:
    from adapters.numpy_runtime import np

from .camera_motion import WorldCameraMotion
from .candidates import detect_world_candidates, _components, _intersects
from .learned_detector import LearnedWorldDetector
from .models import PixelRect, WorldCandidate, WorldSceneROI
from ..opencv_backend import OpenCvComputeBackend, create_opencv_backend


def _integral(values: np.ndarray) -> np.ndarray:
    return np.pad(values.astype(np.float32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)


def _rect_sum(ii: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> float:
    return float(ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0])


def _iou(a: PixelRect, b: PixelRect) -> float:
    iw = max(0, min(a.right, b.right) - max(a.left, b.left))
    ih = max(0, min(a.bottom, b.bottom) - max(a.top, b.top))
    intersection = iw * ih
    union = a.width * a.height + b.width * b.height - intersection
    return intersection / union if union else 0.0


def _intersection_over_smaller(a: PixelRect, b: PixelRect) -> float:
    """Containment-aware overlap for nested multi-scale proposals."""
    iw = max(0, min(a.right, b.right) - max(a.left, b.left))
    ih = max(0, min(a.bottom, b.bottom) - max(a.top, b.top))
    smaller = min(a.width * a.height, b.width * b.height)
    return iw * ih / smaller if smaller else 0.0


def _overlap_fraction(rect: PixelRect, region: PixelRect | None) -> float:
    """Fraction of ``rect`` covered by a region, without assigning semantics."""
    if region is None:
        return 0.0
    width = max(0, min(rect.right, region.right)-max(rect.left, region.left))
    height = max(0, min(rect.bottom, region.bottom)-max(rect.top, region.top))
    return width*height/max(1.0, rect.width*rect.height)


def _annotate_self_avatar_attention(candidate: WorldCandidate,
                                    scene: WorldSceneROI) -> WorldCandidate:
    """Mark a likely self view without deleting its UNKNOWN observation.

    Every detector sees the original pixels. Downstream attention may ignore a
    large, centred, bottom-anchored subject that is probably the local avatar;
    later overhead/group evidence can override the hint for an overlapping NPC.
    """
    region = scene.self_avatar_rect
    if region is None:
        return candidate
    appearance = dict(candidate.appearance)
    overlap = _overlap_fraction(candidate.rect, region)
    is_subject = candidate.kind in {"unknown_subject_candidate", "unknown_subject_probe"}
    center_x = (candidate.rect.left+candidate.rect.right)/2.0
    centered = abs(center_x-(region.left+region.right)/2.0) <= region.width*.22
    bottom_gap = abs(candidate.rect.bottom-region.bottom)/max(1.0, region.height)
    bottom_anchored = bottom_gap <= .14
    substantial = candidate.rect.height >= region.height*.28
    suppression_hint = bool(
        is_subject and overlap >= .72 and centered and bottom_anchored and substantial)
    appearance.update({
        "self_avatar_region_overlap": round(overlap, 4),
        "possible_self_avatar_overlap": overlap >= .60,
        "self_avatar_bottom_anchored": bottom_anchored,
        "self_avatar_suppression_hint": suppression_hint,
        "self_avatar_evidence_role": "ATTENTION_SUPPRESS_ONLY",
    })
    return replace(candidate, appearance=appearance)


def _same_vertical_attention_region(a: PixelRect, b: PixelRect) -> bool:
    """Return whether two generic windows are likely slices of one subject.

    The generic detector uses several sliding, vertical windows.  Adjacent
    windows over the torso/head of one visual subject can have fairly low IoU,
    which ordinary NMS intentionally does not suppress.  That is useful for
    object proposals in general, but here it creates multiple *UNKNOWN*
    subject tracks for one body.

    This remains appearance/geometry-only: it makes no entity or role claim.
    It deliberately requires horizontal alignment and substantial vertical
    overlap.  Thus two units standing side-by-side are retained even when their
    boxes touch, while vertically offset crop fragments of one body compete for
    a single attention region.
    """
    intersection_width = max(0, min(a.right, b.right) - max(a.left, b.left))
    intersection_height = max(0, min(a.bottom, b.bottom) - max(a.top, b.top))
    center_ax = (a.left + a.right) / 2.0
    center_bx = (b.left + b.right) / 2.0
    horizontal_alignment = abs(center_ax - center_bx) <= .60 * min(a.width, b.width)
    substantial_vertical_overlap = intersection_height >= .40 * min(a.height, b.height)
    narrow_shared_column = intersection_width >= .35 * min(a.width, b.width)
    return horizontal_alignment and substantial_vertical_overlap and narrow_shared_column


_CAMERA_MOTION = WorldCameraMotion()

class World3DPerceptionV2:
    """One-frame-at-a-time stateful proposal generator.

    Global translation is estimated on a small luminance image.  Only motion
    left after that translation is entity-motion evidence.  Generic proposals
    use local contrast, edge density and vertical geometry; those properties do
    not assign NPC/MOB/PLAYER semantics.
    """

    def __init__(self, *, downsample: int = 4, max_generic: int = 6,
                 compute_backend: OpenCvComputeBackend | None = None,
                 learned_detector: LearnedWorldDetector | None = None,
                 proposal_mode: str = "HYBRID") -> None:
        self.downsample = max(2, int(downsample))
        self.max_generic = max(1, int(max_generic))
        self.compute_backend = (compute_backend if compute_backend is not None
                                else create_opencv_backend())
        # Optional and additive.  A learned model is one evidence source, not
        # a replacement for the cheap detectors and never an entity authority.
        self.learned_detector = learned_detector
        self.proposal_mode = str(proposal_mode).strip().upper()
        if self.proposal_mode not in {"HYBRID", "YOLO_ONLY"}:
            raise ValueError("proposal_mode must be HYBRID or YOLO_ONLY")
        if self.proposal_mode == "YOLO_ONLY" and self.learned_detector is None:
            raise ValueError("YOLO_ONLY proposal mode requires a learned detector")
        self.previous_gray: np.ndarray | None = None
        self.frame_index = 0
        self.last_diagnostics: dict[str, object] = {}

    def reset(self) -> None:
        self.previous_gray = None
        self.frame_index = 0
        self.last_diagnostics = {}

    @staticmethod
    def _gray(raw: bytes, width: int, height: int, step: int,
              compute_backend: OpenCvComputeBackend | None = None) -> np.ndarray:
        if compute_backend is not None:
            return compute_backend.world3d_gray(raw, width, height, step)
        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        sample = pixels[::step, ::step, :3].astype(np.float32)
        return .114 * sample[:, :, 0] + .587 * sample[:, :, 1] + .299 * sample[:, :, 2]

    @staticmethod
    def _camera_translation(previous: np.ndarray, current: np.ndarray, limit: int = 10) -> tuple[int, int, float]:
        """Camera translation at the image centre: current(x,y) ~= previous(x-dx,y-dy).

        Live 2026-09-30: the former whole-frame correlation stayed at ~0 during
        camera turns (screen-fixed AIPC strip/HUD/orbit-centre avatar), so the
        residual/static evidence and the track coasting never saw the turn.
        ``camera_motion`` measures two world crops beside the avatar instead.
        ``limit`` keeps its historical unit (half-resolution cells).
        """
        if previous.shape != current.shape or min(current.shape) < 12:
            return 0, 0, 0.0
        motion = _CAMERA_MOTION.hypotheses(previous, current)[0]
        if motion.name == "identity":
            return 0, 0, 0.0
        height, width = current.shape
        dx, dy = motion.shift_at(width / 2, height / 2)
        lim = 2 * min(int(limit), max(1, min(current.shape) // 6))
        if abs(dx) > lim or abs(dy) > lim:
            return 0, 0, 0.0
        confidence = max(0.0, min(1.0, float(motion.response)))
        if confidence < .08:
            return 0, 0, confidence
        return int(round(dx)), int(round(dy)), confidence

    @staticmethod
    def _aligned_residual(previous: np.ndarray, current: np.ndarray, dx: int, dy: int) -> np.ndarray:
        residual = np.zeros_like(current, dtype=np.float32)
        py0, py1 = max(0, -dy), min(previous.shape[0], previous.shape[0] - dy)
        px0, px1 = max(0, -dx), min(previous.shape[1], previous.shape[1] - dx)
        cy0, cy1 = py0 + dy, py1 + dy
        cx0, cx1 = px0 + dx, px1 + dx
        residual[cy0:cy1, cx0:cx1] = np.abs(current[cy0:cy1, cx0:cx1] - previous[py0:py1, px0:px1])
        return residual

    def _feature(self, gray: np.ndarray, residual: np.ndarray, rect: PixelRect,
                 scene: WorldSceneROI, camera: tuple[int, int, float]) -> dict[str, float | str | bool]:
        step = self.downsample
        x0, x1 = max(0, rect.left // step), min(gray.shape[1], math.ceil(rect.right / step))
        y0, y1 = max(0, rect.top // step), min(gray.shape[0], math.ceil(rect.bottom / step))
        patch = gray[y0:y1, x0:x1]
        motion = residual[y0:y1, x0:x1]
        if not patch.size:
            return {}
        gx = np.abs(np.diff(patch, axis=1)).mean() if patch.shape[1] > 1 else 0.0
        gy = np.abs(np.diff(patch, axis=0)).mean() if patch.shape[0] > 1 else 0.0
        cx = (rect.left + rect.right) / 2
        center = 1.0 - min(1.0, abs(cx - (scene.rect.left + scene.rect.right) / 2) /
                           max(1.0, scene.rect.width / 2))
        aspect = rect.width / max(1.0, rect.height)
        body = max(0.0, 1.0 - abs(aspect - .52) / .72) if rect.height >= 24 else 0.0
        residual_score = min(1.0, float(np.mean(motion)) / 30.0) if motion.size else 0.0
        edge = min(1.0, float(gx + gy) / 55.0)
        contrast = min(1.0, float(np.std(patch)) / 45.0)
        static = max(0.0, min(1.0, .72 - residual_score * .8 + camera[2] * .18))
        return {
            "foreground_contrast": round(contrast, 4),
            "edge_density": round(edge, 4),
            "body_geometry": round(body, 4),
            "screen_center_relevance": round(center, 4),
            "residual_motion": round(residual_score, 4),
            "independent_motion": round(residual_score, 4),
            "static_scene_score": round(static, 4),
            "camera_motion_dx": camera[0] * step,
            "camera_motion_dy": camera[1] * step,
            "camera_motion_confidence": round(camera[2], 4),
            "proposal_semantics": "UNKNOWN",
        }

    def _generic(self, gray: np.ndarray, residual: np.ndarray, scene: WorldSceneROI,
                 camera: tuple[int, int, float]) -> list[WorldCandidate]:
        step = self.downsample
        gy = np.zeros_like(gray); gx = np.zeros_like(gray)
        gy[1:] = np.abs(gray[1:] - gray[:-1]); gx[:, 1:] = np.abs(gray[:, 1:] - gray[:, :-1])
        edge = np.minimum(80.0, gx + gy)
        ii, ii2, ie = _integral(gray), _integral(gray * gray), _integral(edge)
        ir = _integral(residual)
        candidates: list[WorldCandidate] = []
        scene_x0 = max(0, scene.rect.left // step)
        scene_x1 = scene.rect.right // step
        scene_y0 = max(0, scene.rect.top // step)
        scene_y1 = scene.rect.bottom // step
        scene_cx = (scene.rect.left + scene.rect.right) / 2
        # Multi-scale vertical windows cover humanoid and creature-sized
        # foreground regions without assuming either semantic category.
        # Score every window position for one (ww, hh) at once via the
        # already-built integral images (ii/ii2/ie/ir give an O(1) rect sum
        # each), instead of one Python-level call per position -- this is
        # the same arithmetic _rect_sum did, just batched with numpy
        # broadcasting. np.nonzero on a C-contiguous 2D array yields indices
        # in row-major order, matching the original "for y0: for x0:"
        # nesting exactly, so tie-break/insertion order is unchanged.
        for ww, hh in ((8, 16), (12, 24), (18, 30)):
            stride_x, stride_y = max(3, ww // 2), max(4, hh // 2)
            y0_stop = min(gray.shape[0] - hh, scene_y1)
            x0_stop = min(gray.shape[1] - ww, scene_x1)
            ys = np.arange(scene_y0, y0_stop, stride_y)
            xs = np.arange(scene_x0, x0_stop, stride_x)
            if ys.size == 0 or xs.size == 0:
                continue
            area = float(ww * hh)
            Y0, X0 = ys[:, None], xs[None, :]
            Y1, X1 = Y0 + hh, X0 + ww

            def rect_sum(integral, Y0=Y0, Y1=Y1, X0=X0, X1=X1):
                return integral[Y1, X1] - integral[Y0, X1] - integral[Y1, X0] + integral[Y0, X0]

            mean = rect_sum(ii) / area
            variance = np.maximum(0.0, rect_sum(ii2) / area - mean * mean)
            contrast = np.minimum(1.0, np.sqrt(variance) / 45.0)
            edge_score = np.minimum(1.0, rect_sum(ie) / area / 35.0)
            motion = np.minimum(1.0, rect_sum(ir) / area / 30.0)
            aspect = ww / hh
            geometry = max(0.0, 1.0 - abs(aspect - .52) / .72)
            center_x = (xs + ww / 2.0) * step
            center = 1.0 - np.minimum(1.0, np.abs(center_x - scene_cx) / max(1.0, scene.rect.width / 2))
            score = (.27 * contrast + .25 * edge_score + .19 * geometry
                     + .17 * motion + .12 * center[None, :])
            passed = (score >= .43) & ~((contrast < .28) & (motion < .22))
            for pi, pj in zip(*np.nonzero(passed)):
                y0, x0 = int(ys[pi]), int(xs[pj])
                rect = PixelRect(x0 * step, y0 * step, (x0 + ww) * step, (y0 + hh) * step)
                if any(_intersects(rect, ex) for ex in scene.excluded_rects):
                    continue
                position_score = float(score[pi, pj])
                appearance = self._feature(gray, residual, rect, scene, camera)
                appearance.update({"shape": "generic_subject_proposal", "proposal_score": round(position_score, 4)})
                candidates.append(WorldCandidate(
                    "unknown_subject_candidate", rect, min(.78, .38 + .48 * position_score),
                    "generic foreground proposal: local contrast + edges + geometry + residual motion",
                    appearance=appearance,
                    candidate_labels=("generic_subject_like", "foreground_like"),
                ))

        candidates.sort(key=lambda c: float(c.appearance.get("proposal_score", 0)), reverse=True)
        kept: list[WorldCandidate] = []
        suppressed_spatial_duplicates = 0
        for candidate in candidates:
            if any(_iou(candidate.rect, other.rect) > .20
                   or _intersection_over_smaller(candidate.rect, other.rect) > .62
                   or _same_vertical_attention_region(candidate.rect, other.rect)
                   for other in kept):
                suppressed_spatial_duplicates += 1
                continue
            kept.append(candidate)
            if len(kept) >= self.max_generic:
                break
        # Persist only a compact count.  The individual suppression is an
        # internal candidate-budget decision, never a semantic rejection.
        self._last_generic_spatial_duplicates = suppressed_spatial_duplicates
        return kept

    def process(self, raw: bytes, width: int, height: int, scene: WorldSceneROI, *,
                precomputed_learned=None) -> tuple[WorldCandidate, ...]:
        """``precomputed_learned``: candidates a capture-driven detector feed
        already produced for exactly this frame; the learned detector is then
        not invoked here."""
        self.frame_index += 1
        gray = self._gray(raw, width, height, self.downsample, self.compute_backend)
        camera = (0, 0, 0.0)
        residual = np.zeros_like(gray, dtype=np.float32)
        if self.previous_gray is not None and self.previous_gray.shape == gray.shape:
            camera = self._camera_translation(self.previous_gray, gray)
            residual = self._aligned_residual(self.previous_gray, gray, camera[0], camera[1])
        # YOLO_ONLY is the production live mode. OpenCV still supplies camera
        # compensation, appearance features and patch propagation, but it is
        # forbidden from inventing independent candidates/boxes.
        legacy = ([] if self.proposal_mode == "YOLO_ONLY" else
                  list(detect_world_candidates(raw, width, height, scene)))
        generic = ([] if self.proposal_mode == "YOLO_ONLY" else
                   self._generic(gray, residual, scene, camera))
        learned: list[WorldCandidate] = []
        learned_error: str | None = None
        if precomputed_learned is not None:
            learned = list(precomputed_learned)
        elif self.learned_detector is not None:
            try:
                learned = list(self.learned_detector.detect(raw, width, height, scene))
            except Exception as exc:  # model failure must not kill perception
                learned_error = f"{type(exc).__name__}:{exc}"

        enriched: list[WorldCandidate] = []
        for candidate in (*legacy, *learned):
            appearance = dict(candidate.appearance)
            appearance.update(self._feature(gray, residual, candidate.rect, scene, camera))
            # Existing nameplate/symbol algorithms remain only appearance hints.
            if "possible_nameplate_like" in candidate.candidate_labels:
                appearance["nameplate_evidence_role"] = "SECONDARY"
            enriched.append(replace(candidate, appearance=appearance))

        merged = enriched[:]
        for proposal in generic:
            # Prefer the legacy crop when it describes the same UNKNOWN subject,
            # but merge the v2 features into it instead of emitting two tracks.
            overlap = next((i for i, item in enumerate(merged)
                            if item.kind == "unknown_subject_candidate" and _iou(item.rect, proposal.rect) > .28), None)
            if overlap is None:
                merged.append(proposal)
            else:
                item = merged[overlap]
                appearance = {**proposal.appearance, **item.appearance}
                labels = tuple(dict.fromkeys((*item.candidate_labels, *proposal.candidate_labels)))
                merged[overlap] = replace(item, confidence=max(item.confidence, proposal.confidence),
                                          appearance=appearance, candidate_labels=labels,
                                          evidence=f"{item.evidence}; {proposal.evidence}")

        # The avatar band is not an excluded ROI. Annotate probable self
        # detections only after all detector paths have seen the original image.
        merged = [_annotate_self_avatar_attention(item, scene) for item in merged]

        # Candidate budgeting is appearance-only suppression, not semantic
        # recognition. Keep the strongest UNKNOWN hypotheses while preventing
        # foliage/rocks and nested multi-scale windows from flooding tracking,
        # OCR and active perception.
        rank = {"unknown_symbol_candidate": 5, "unknown_subject_candidate": 4,
                "unknown_subject_probe": 4, "unknown_object_candidate": 3,
                "unknown_scene_candidate": 2, "visual_candidate": 1}
        budgets = {"unknown_symbol_candidate": 4, "unknown_subject_candidate": 8,
                   "unknown_subject_probe": 3, "unknown_object_candidate": 4,
                   "unknown_scene_candidate": 2, "visual_candidate": 2}
        ordered = sorted(merged, key=lambda item: (
            rank.get(item.kind, 0), item.confidence,
            float(item.appearance.get("proposal_score", 0))), reverse=True)
        reduced: list[WorldCandidate] = []
        counts: dict[str, int] = {}
        suppressed_overlap = 0
        suppressed_budget = 0
        for item in ordered:
            stronger_overlap = any(
                rank.get(kept.kind, 0) > rank.get(item.kind, 0)
                and (_iou(item.rect, kept.rect) > .18
                     or _intersection_over_smaller(item.rect, kept.rect) > .55)
                for kept in reduced)
            same_family_overlap = any(
                kept.kind == item.kind
                and (_iou(item.rect, kept.rect) > .28
                     or _intersection_over_smaller(item.rect, kept.rect) > .72
                     # Generic vertical proposal fragments are not independent
                     # visual subjects.  This is intentionally limited to the
                     # generic family, so distinct legacy detector candidates
                     # remain available for later evidence association.
                     or (item.kind == "unknown_subject_candidate"
                         and "generic_subject_like" in item.candidate_labels
                         and "generic_subject_like" in kept.candidate_labels
                         and _same_vertical_attention_region(item.rect, kept.rect)))
                for kept in reduced)
            if stronger_overlap or same_family_overlap:
                suppressed_overlap += 1
                continue
            if counts.get(item.kind, 0) >= budgets.get(item.kind, 3):
                suppressed_budget += 1
                continue
            reduced.append(item)
            counts[item.kind] = counts.get(item.kind, 0) + 1

        self.previous_gray = gray
        self.last_diagnostics = {
            "version": "world3d_v2", "frame_index": self.frame_index,
            "proposal_mode": self.proposal_mode,
            "camera_motion_px": {"dx": camera[0] * self.downsample, "dy": camera[1] * self.downsample,
                                 "confidence": round(camera[2], 4)},
            "legacy_candidates": len(legacy), "generic_candidates": len(generic),
            "learned_candidates": len(learned),
            "learned_detector": (
                {**self.learned_detector.last_diagnostics,
                 **({"runtime_error": learned_error} if learned_error else {})}
                if self.learned_detector is not None else {"status": "disabled"}),
            "pre_filter_candidates": len(merged),
            "suppressed_overlap": suppressed_overlap,
            "suppressed_spatial_duplicates": getattr(self, "_last_generic_spatial_duplicates", 0),
            "suppressed_budget": suppressed_budget,
            "self_avatar_attention_hints": sum(
                bool(item.appearance.get("self_avatar_suppression_hint")) for item in reduced),
            "output_candidates": len(reduced),
            "opencv_compute": (self.compute_backend.diagnostics()
                               if self.compute_backend is not None
                               else {"requested": "AUTO", "active": "NUMPY",
                                     "reason": "opencv_unavailable"}),
        }
        return tuple(sorted(reduced, key=lambda c: c.confidence, reverse=True))
