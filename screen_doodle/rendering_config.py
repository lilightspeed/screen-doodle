from __future__ import annotations

import json
import os
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Config dataclass — all tunable stroke parameters in one place
# ---------------------------------------------------------------------------


@dataclass
class StrokeConfig:
    """Tuning knobs for velocity-sensitive width and rendering quality.

    Every field has a sensible default.  Missing fields in the JSON file
    are filled from these defaults, so adding a new field here is
    backward-compatible with existing config files.
    """

    # ── Velocity-to-width mapping ────────────────────────────────────────
    sample_interval: int = 4
    """Recalculate width every N mouse events (lower frequency = smoother)."""

    smoothing_alpha: float = 0.12
    """Exponential smoothing factor (lower = smoother/slower response)."""

    thin_mult: float = 0.4
    """Width multiplier at max speed (fastest = thin)."""

    thick_mult: float = 2.5
    """Width multiplier at min speed (slowest = thick)."""

    ref_dist: float = 20.0
    """Pixel distance at which the velocity curve is roughly halfway."""

    power_exponent: float = 0.7
    """Shape of the velocity→width curve (<1 = more sensitivity at low speeds)."""

    # ── Rendering quality ────────────────────────────────────────────────
    min_segment_width: float = 0.5
    """Clamp per-segment width to at least this value (avoids zero-width artifacts)."""

    preview_antialias: bool = False
    """Whether to enable antialiasing on the in-progress preview.
    When False (default), the preview shows visible stair‑step edges,
    making the smooth final render clearly distinguishable on release."""

    preview_opacity: float = 0.7
    """Opacity multiplier for the in-progress stroke preview."""

    highlighter_opacity_scale: float = 0.3
    """Additional opacity multiplier for the highlighter tool."""

    highlighter_width_scale: float = 4.0
    """Width multiplier for the highlighter tool (applied on top of base width)."""

    interpolation_segments: int = 8
    """Catmull-Rom sub‑segments per control‑point pair (higher = smoother curve)."""

    subdivision_pixel_gap: float = 4.0
    """Max pixel distance between sub‑segments when subdividing a sparse 2‑point
    initial stroke (lower = finer subdivision, more computationally expensive).
    Only used during the transient phase before enough mouse events arrive for
    Catmull-Rom interpolation."""

    max_point_gap: float = 8.0
    """Max pixel distance between consecutive raw input points before automatic
    densification inserts Catmull-Rom interpolated intermediate points.
    Smaller values = denser point cloud = smoother curves (slightly more CPU)."""

    max_densify_insert: int = 16
    """Safety cap on the number of intermediate points inserted per densification
    step (prevents explosion from extremely sparse input)."""


# ---------------------------------------------------------------------------
# JSON file management
# ---------------------------------------------------------------------------

_CONFIG_FILE = "stroke_profile.json"


def _resolve_config_path() -> str:
    """Return ``<project-root>/stroke_profile.json``."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        _CONFIG_FILE,
    )


def _write_defaults(path: str) -> None:
    """Write a config file with all default values (and a comment header)."""
    cfg = StrokeConfig()
    data = {
        "_comment": (
            "Stroke tuning profile.\n"
            "Edit any value and restart the app to apply.\n"
            "Delete this file to regenerate defaults."
        ),
        "velocity": {
            "sample_interval": cfg.sample_interval,
            "smoothing_alpha": cfg.smoothing_alpha,
            "thin_mult": cfg.thin_mult,
            "thick_mult": cfg.thick_mult,
            "ref_dist": cfg.ref_dist,
            "power_exponent": cfg.power_exponent,
        },
        "rendering": {
            "min_segment_width": cfg.min_segment_width,
            "preview_antialias": cfg.preview_antialias,
            "preview_opacity": cfg.preview_opacity,
            "highlighter_opacity_scale": cfg.highlighter_opacity_scale,
            "highlighter_width_scale": cfg.highlighter_width_scale,
            "interpolation_segments": cfg.interpolation_segments,
            "subdivision_pixel_gap": cfg.subdivision_pixel_gap,
            "max_point_gap": cfg.max_point_gap,
            "max_densify_insert": cfg.max_densify_insert,
        },
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_stroke_config() -> StrokeConfig:
    """Load the config from disk, or create it with defaults.

    Returns a ``StrokeConfig`` populated from the JSON file (missing or
    invalid fields fall back to defaults).
    """
    path = _resolve_config_path()

    if not os.path.exists(path):
        _write_defaults(path)
        return StrokeConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return StrokeConfig()

    cfg = StrokeConfig()

    # --- velocity section ---
    vel = data.get("velocity", {})
    try:
        cfg.sample_interval = int(vel.get("sample_interval", cfg.sample_interval))
    except (TypeError, ValueError):
        pass
    try:
        cfg.smoothing_alpha = float(vel.get("smoothing_alpha", cfg.smoothing_alpha))
    except (TypeError, ValueError):
        pass
    try:
        cfg.thin_mult = float(vel.get("thin_mult", cfg.thin_mult))
    except (TypeError, ValueError):
        pass
    try:
        cfg.thick_mult = float(vel.get("thick_mult", cfg.thick_mult))
    except (TypeError, ValueError):
        pass
    try:
        cfg.ref_dist = float(vel.get("ref_dist", cfg.ref_dist))
    except (TypeError, ValueError):
        pass
    try:
        cfg.power_exponent = float(vel.get("power_exponent", cfg.power_exponent))
    except (TypeError, ValueError):
        pass

    # --- rendering section ---
    rnd = data.get("rendering", {})
    try:
        cfg.preview_antialias = bool(rnd.get("preview_antialias", cfg.preview_antialias))
    except (TypeError, ValueError):
        pass
    try:
        cfg.min_segment_width = float(rnd.get("min_segment_width", cfg.min_segment_width))
    except (TypeError, ValueError):
        pass
    try:
        cfg.preview_opacity = float(rnd.get("preview_opacity", cfg.preview_opacity))
    except (TypeError, ValueError):
        pass
    try:
        cfg.highlighter_opacity_scale = float(rnd.get("highlighter_opacity_scale", cfg.highlighter_opacity_scale))
    except (TypeError, ValueError):
        pass
    try:
        cfg.highlighter_width_scale = float(rnd.get("highlighter_width_scale", cfg.highlighter_width_scale))
    except (TypeError, ValueError):
        pass
    try:
        cfg.interpolation_segments = int(rnd.get("interpolation_segments", cfg.interpolation_segments))
    except (TypeError, ValueError):
        pass
    try:
        cfg.subdivision_pixel_gap = float(rnd.get("subdivision_pixel_gap", cfg.subdivision_pixel_gap))
    except (TypeError, ValueError):
        pass
    try:
        cfg.max_point_gap = float(rnd.get("max_point_gap", cfg.max_point_gap))
    except (TypeError, ValueError):
        pass
    try:
        cfg.max_densify_insert = int(rnd.get("max_densify_insert", cfg.max_densify_insert))
    except (TypeError, ValueError):
        pass

    return cfg


# Module-level singleton — loaded once on first import.
cfg = load_stroke_config()
