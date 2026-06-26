from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import QPointF

from .models import Stroke, ToolType
from .rendering_config import cfg

# Only these tools get dynamic width based on drawing speed.
_VELOCITY_TOOLS = {ToolType.PEN, ToolType.PEN2, ToolType.PEN3}


class StrokeManager(QObject):
    """Manages the ordered list of strokes with undo/redo support."""

    data_changed = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.strokes: list[Stroke] = []
        self.redo_stack: list[Stroke] = []
        self._current: Stroke | None = None
        self._velocity_counter: int = 0
        self._accumulated_dist: float = 0.0

    def start_stroke(
        self,
        point: QPointF,
        color,
        width: float,
        opacity: float,
        tool: ToolType,
    ) -> Stroke:
        """Begin a new stroke at the given point. Clears the redo stack.

        The first real mouse-move event (via ``add_point``) will *absorb* this
        starting point — replacing it rather than appending — so the
        press-position → first-move segment (a long straight line when drawing
        fast) is never created.  The stroke visibly starts at the first
        movement position.
        """
        self.redo_stack.clear()
        self._velocity_counter = 0
        self._accumulated_dist = 0.0
        self._absorb_first_point = True
        self._current = Stroke(
            points=[point],
            color=color,
            width=width,
            opacity=opacity,
            tool=tool,
        )
        # The first point has no predecessor for velocity calculation,
        # so it gets the base width.
        self._current.point_widths = [width]
        return self._current

    def add_point(self, point: QPointF) -> None:
        """Append a point to the in-progress stroke.

        **First-point absorption**
        The very first call after ``start_stroke`` *replaces* the press
        position instead of appending — this eliminates the long straight
        line that appears when the mouse has already moved a significant
        distance by the time the first ``mouseMoveEvent`` fires.

        For velocity-sensitive tools (PEN / PEN2 / PEN3), the width is
        recalculated only every ``_SAMPLE_INTERVAL`` points using the
        *average* distance over that window.  Between recalculations the
        last computed width is reused, which reduces jitter and makes the
        stroke feel more stable.

        After appending, the segment is automatically densified when the
        gap exceeds *max_point_gap* — Catmull-Rom interpolated intermediate
        points (carrying curvature from neighbouring points) are injected
        so the renderer always has dense geometry for smooth curves.
        """
        if self._current is None:
            return

        # ── Absorb the first real move into the press-position ──────────
        # This discards the press→first-move "straight line" artifact and
        # makes the stroke visibly start at the first movement position.
        if self._absorb_first_point:
            self._current.points[0] = point
            # Width stays at base_width (set in start_stroke) — there is no
            # predecessor distance to compute a velocity yet.
            self._absorb_first_point = False
            return

        last = self._current.points[-1]
        dist = math.hypot(point.x() - last.x(), point.y() - last.y())

        tool = self._current.tool
        if tool in _VELOCITY_TOOLS:
            self._accumulated_dist += dist
            self._velocity_counter += 1

            if self._velocity_counter >= cfg.sample_interval:
                avg_dist = self._accumulated_dist / cfg.sample_interval
                prev = self._current.point_widths[-1] if self._current.point_widths else None
                w = self._compute_point_width(self._current.width, avg_dist, prev)
                self._velocity_counter = 0
                self._accumulated_dist = 0.0
            else:
                w = self._current.point_widths[-1] if self._current.point_widths else self._current.width
        else:
            w = self._current.width

        self._current.points.append(point)
        self._current.point_widths.append(w)

        # ── Densify the segment just added ──────────────────────────────
        self._densify_last_segment()

    # ------------------------------------------------------------------
    # Adaptive segment densification
    # ------------------------------------------------------------------

    def _densify_last_segment(self) -> None:
        """Insert Catmull-Rom interpolated points on the last segment if sparse.

        When the distance between the last two collected points exceeds
        *max_point_gap*, this method replaces the raw segment with a set of
        Hermite-interpolated sub‑segments that carry through the curvature
        implied by earlier neighbouring points.  The result is a uniformly
        dense point stream — even near the start of a fast stroke — so the
        Catmull-Rom renderer always has enough geometry to produce smooth
        curves without relying on collinear subdivision.

        **4‑point Catmull‑Rom window**

            [Pᵢ₋₁, P_start, P_end, Pᵢ₊₁]

        *P_start/P_end* are the last two raw input points.  *Pᵢ₋₁* is drawn
        from the available history (or synthesised by reflection when this
        is the very first segment).  *Pᵢ₊₁* is extrapolated from the current
        direction so the tangent at *P_end* has a natural look‑ahead.

        Widths are linearly interpolated along the segment — the velocity‑
        derived profile from the real mouse events is preserved unchanged.
        """
        pts = self._current.points
        wids = self._current.point_widths
        n = len(pts)
        if n < 2:
            return

        p_start = pts[-2]
        p_end = pts[-1]
        w_start = wids[-2]
        w_end = wids[-1]

        dx = p_end.x() - p_start.x()
        dy = p_end.y() - p_start.y()
        seg_dist = math.hypot(dx, dy)

        if seg_dist <= cfg.max_point_gap:
            return

        num = min(int(seg_dist / cfg.max_point_gap), cfg.max_densify_insert)
        if num < 1:
            return

        # ---- Build the 4-point Catmull-Rom window ----
        # Temporarily pop the endpoint — it goes back after interpolation.
        pts.pop()
        wids.pop()
        n -= 1

        if n >= 2:
            p_prev = pts[-2]          # Pᵢ₋₂ — real predecessor
        else:
            # Very first segment — reflect P_end across P_start.
            p_prev = QPointF(
                2 * p_start.x() - p_end.x(),
                2 * p_start.y() - p_end.y(),
            )

        # Look‑ahead point (direction-keeping extrapolation).
        p_next = QPointF(
            2 * p_end.x() - p_start.x(),
            2 * p_end.y() - p_start.y(),
        )

        # ---- Centripetal (α = 0.5) knots ----
        d_pp = math.hypot(p_start.x() - p_prev.x(), p_start.y() - p_prev.y())
        d_pe = math.hypot(p_end.x() - p_start.x(), p_end.y() - p_start.y())
        d_en = math.hypot(p_next.x() - p_end.x(), p_next.y() - p_end.y())

        k0 = 0.0
        k1 = k0 + d_pp ** 0.5
        k2 = k1 + d_pe ** 0.5
        k3 = k2 + d_en ** 0.5

        interval = k2 - k1
        if interval < 1e-12:
            # Degenerate — fall back to linear to avoid division by zero.
            for j in range(1, num + 1):
                t = j / (num + 1)
                pts.append(QPointF(
                    p_start.x() + t * dx,
                    p_start.y() + t * dy,
                ))
                wids.append(w_start + t * (w_end - w_start))
            pts.append(p_end)
            wids.append(w_end)
            return

        # ---- Standard Catmull-Rom tangents ----
        # Tangent at P_start: (P_end − Pᵢ₋₁) / (k2 − k0)
        dx_s = (p_end.x() - p_prev.x()) / (k2 - k0)
        dy_s = (p_end.y() - p_prev.y()) / (k2 - k0)

        # Tangent at P_end:   (Pᵢ₊₁ − P_start) / (k3 − k1)
        dx_e = (p_next.x() - p_start.x()) / (k3 - k1)
        dy_e = (p_next.y() - p_start.y()) / (k3 - k1)

        # ---- Evaluate cubic Hermite curve ----
        for j in range(1, num + 1):
            τ = j / (num + 1)
            τ2 = τ * τ
            τ3 = τ2 * τ

            h00 = 2 * τ3 - 3 * τ2 + 1
            h10 = τ3 - 2 * τ2 + τ
            h01 = -2 * τ3 + 3 * τ2
            h11 = τ3 - τ2

            x = (h00 * p_start.x() + h10 * interval * dx_s
                 + h01 * p_end.x() + h11 * interval * dx_e)
            y = (h00 * p_start.y() + h10 * interval * dy_s
                 + h01 * p_end.y() + h11 * interval * dy_e)

            pts.append(QPointF(x, y))
            wids.append(w_start + τ * (w_end - w_start))

        # Restore the original endpoint.
        pts.append(p_end)
        wids.append(w_end)

    # ------------------------------------------------------------------
    # Velocity → width
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_point_width(
        base_width: float,
        distance: float,
        prev_width: float | None,
    ) -> float:
        """Map pixel distance to a smoothed stroke width.

        Small distance (slow) → wide, large distance (fast) → narrow.
        Exponential smoothing prevents width jitter from mouse noise.
        """
        t = min(distance / cfg.ref_dist, 1.0)
        # Inverted curve: t=0 → thick, t=1 → thin
        raw_mult = cfg.thick_mult - (cfg.thick_mult - cfg.thin_mult) * (t ** cfg.power_exponent)

        if prev_width is not None:
            prev_mult = prev_width / base_width
            smoothed = cfg.smoothing_alpha * raw_mult + (1 - cfg.smoothing_alpha) * prev_mult
        else:
            smoothed = raw_mult

        return base_width * smoothed

    # ------------------------------------------------------------------
    # Stroke lifecycle
    # ------------------------------------------------------------------

    def end_stroke(self) -> Stroke | None:
        """Finalize the current stroke. Returns it, or None if too short."""
        if self._current is None:
            return None

        # Discard strokes with fewer than 2 points
        if len(self._current.points) < 2:
            self._current = None
            return None

        finalized = self._current
        self.strokes.append(finalized)
        self._current = None
        self.data_changed.emit()
        return finalized

    def undo(self) -> bool:
        """Undo the last stroke. Returns True if anything was undone."""
        if not self.strokes:
            return False
        stroke = self.strokes.pop()
        self.redo_stack.append(stroke)
        self.data_changed.emit()
        return True

    def redo(self) -> bool:
        """Redo the last undone stroke. Returns True if anything was redone."""
        if not self.redo_stack:
            return False
        stroke = self.redo_stack.pop()
        self.strokes.append(stroke)
        self.data_changed.emit()
        return True

    def clear(self) -> None:
        """Remove all strokes and clear redo history."""
        self.strokes.clear()
        self.redo_stack.clear()
        self._current = None
        self.data_changed.emit()

    def preview_stroke(self) -> Stroke | None:
        """Return the in-progress stroke for real-time preview rendering."""
        return self._current

    def get_strokes(self) -> list[Stroke]:
        """Return a copy of the finalized stroke list."""
        return list(self.strokes)
