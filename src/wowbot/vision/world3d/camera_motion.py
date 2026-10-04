"""Screen-space camera motion from the World3D luminance image.

Live 2026-09-30 (PID 3324 feed traces): a whole-frame phase correlation stayed
at ~0 px while camera turns moved detections 20-100 px per frame.  The
screen-fixed AIPC pixel strip, HUD text and the avatar the camera orbits
dominate a whole-frame correlation.  Only two world crops are measured here:
left and right of the avatar, below the strip and above the action bars.

The two crops legitimately disagree while the avatar runs (forward motion
expands the image: the left crop moves left, the right crop right) and when
one crop locks onto the near ground and the other onto far scenery during an
orbit.  Instead of discarding such frames the caller receives every plausible
hypothesis (left, right, their mean, the similarity transform explaining both,
and identity) and may pick the one that best explains the detections.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from src.adapters.numpy_runtime import np
except ModuleNotFoundError:  # pragma: no cover - installed package path
    from adapters.numpy_runtime import np

# Fractions of the image; the avatar column (.46-.54) is excluded.
WORLD_BAND_Y = (.20, .66)
WORLD_CROPS_X = ((.04, .46), (.54, .92))
MAX_SCALE_STEP = .12


@dataclass(frozen=True, slots=True)
class MotionHypothesis:
    """``x' = scale * x + tx`` (same for y), in the measured image's pixels."""
    name: str
    scale: float
    tx: float
    ty: float
    response: float

    def shift_at(self, x: float, y: float) -> tuple[float, float]:
        return (self.scale-1.)*x + self.tx, (self.scale-1.)*y + self.ty

    def warp(self, step: float = 1.) -> Any:
        matrix = np.eye(2, 3)
        matrix[0, 0] = matrix[1, 1] = self.scale
        matrix[0, 2], matrix[1, 2] = self.tx*step, self.ty*step
        return matrix


IDENTITY = MotionHypothesis("identity", 1., 0., 0., 0.)


class WorldCameraMotion:
    def __init__(self, *, min_response: float = .1) -> None:
        self.min_response = float(min_response)
        self._windows: dict[tuple[int, int], Any] = {}
        self.last_crops: list[tuple[float, float, float] | None] = []

    def hypotheses(self, previous: Any, current: Any) -> list[MotionHypothesis]:
        """Plausible motions, best default first (identity always last)."""
        import cv2
        height, width = current.shape
        y0, y1 = int(height*WORLD_BAND_Y[0]), int(height*WORLD_BAND_Y[1])
        crops: list[tuple[float, float, float, float] | None] = []
        for fx0, fx1 in WORLD_CROPS_X:
            x0, x1 = int(width*fx0), int(width*fx1)
            if x1-x0 < 16 or y1-y0 < 16:
                crops.append(None)
                continue
            p = np.ascontiguousarray(previous[y0:y1, x0:x1], dtype=np.float32)
            c = np.ascontiguousarray(current[y0:y1, x0:x1], dtype=np.float32)
            if float(p.std()) < 2. or float(c.std()) < 2.:
                crops.append(None)  # textureless (sky, fog): no evidence
                continue
            window = self._windows.get(c.shape)
            if window is None:
                window = self._windows[c.shape] = cv2.createHanningWindow(
                    (c.shape[1], c.shape[0]), cv2.CV_32F)
            (sx, sy), response = cv2.phaseCorrelate(p, c, window)
            # Phase correlation is unambiguous up to half the crop; keep a
            # margin and let the response threshold reject weak peaks.
            if (response >= self.min_response and abs(sx) <= (x1-x0)/2.2
                    and abs(sy) <= (y1-y0)/2.2):
                crops.append((float(sx), float(sy), float(response), (x0+x1)/2))
            else:
                crops.append(None)
        self.last_crops = [None if crop is None else crop[:3] for crop in crops]
        valid = [crop for crop in crops if crop is not None]
        result: list[MotionHypothesis] = []
        if len(valid) == 2:
            (lx, ly, lr, lc), (rx, ry, rr, rc) = valid
            yc = (y0+y1)/2
            k = (rx-lx)/max(1., rc-lc)
            if abs(k) <= MAX_SCALE_STEP:
                result.append(MotionHypothesis(
                    "similarity", 1.+k, lx-k*lc, (ly+ry)/2-k*yc, min(lr, rr)))
            result.append(MotionHypothesis(
                "mean", 1., (lx+rx)/2, (ly+ry)/2, min(lr, rr)))
            result.append(MotionHypothesis("left", 1., lx, ly, lr))
            result.append(MotionHypothesis("right", 1., rx, ry, rr))
        elif len(valid) == 1:
            sx, sy, response, _ = valid[0]
            result.append(MotionHypothesis("single", 1., sx, sy, response))
        result.append(IDENTITY)
        return result


def _iou(a, b) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0., right-left)*max(0., bottom-top)
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter/union if union > 0 else 0.


def select_by_detections(hypotheses: list[MotionHypothesis], previous_boxes, current_boxes,
                         step: float) -> tuple[MotionHypothesis, int]:
    """Pick the hypothesis that maps the most previous boxes onto current ones.

    Boxes are client-pixel xyxy; hypotheses are in gray pixels (``step``
    client pixels each).  Ties keep the default (list) order.  Without boxes on
    both frames the first hypothesis is returned unchanged.
    """
    if not hypotheses:
        return IDENTITY, 0
    # BoT-SORT passes numpy arrays: never use their truth value.
    previous = ([] if previous_boxes is None
                else [tuple(float(v) for v in box[:4]) for box in previous_boxes])
    current = ([] if current_boxes is None
               else [tuple(float(v) for v in box[:4]) for box in current_boxes])
    if not previous or not current:
        return hypotheses[0], 0
    def score(hypothesis: MotionHypothesis) -> tuple[int, float]:
        scale, tx, ty = hypothesis.scale, hypothesis.tx*step, hypothesis.ty*step
        matched, total = 0, 0.
        for box in previous:
            moved = (scale*box[0]+tx, scale*box[1]+ty, scale*box[2]+tx, scale*box[3]+ty)
            overlap = max(_iou(moved, other) for other in current)
            if overlap >= .3:
                matched += 1
                total += overlap
        return matched, round(total, 3)

    best, best_score = hypotheses[0], (-1, -1.)
    for hypothesis in hypotheses:
        value = score(hypothesis)
        if value > best_score:
            best, best_score = hypothesis, value
    # Live 2026-10-01 49.5 s (PID 4588): during a fast turn one crop gave -58 px
    # while the NPC box moved +66 px; no image hypothesis explained it and the
    # track was re-born.  A shift measured between a previous and a current
    # box of similar size is tried as well, but wins only by explaining
    # strictly *more* boxes than every image hypothesis.
    if best_score[0] < len(previous):
        for p in previous[:8]:
            for c in current[:8]:
                hp, hc = p[3]-p[1], c[3]-c[1]
                if hp <= 0 or not .75 < hc/hp < 1.33:
                    continue
                dx, dy = (c[0]+c[2]-p[0]-p[2])/2, (c[1]+c[3]-p[1]-p[3])/2
                if abs(dy) > .3*hp:
                    continue
                candidate = MotionHypothesis("detections", 1., dx/step, dy/step, 0.)
                value = score(candidate)
                if value[0] > best_score[0]:
                    best, best_score = candidate, value
    return best, best_score[0]
