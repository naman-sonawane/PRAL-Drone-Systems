"""
PRAL Video Post-Processing Pipeline — CLI Entry Point

Usage:
    python -m video_pipeline.main --input <video> --styles <style1> [style2 ...]
        [--music <audio>] [--output-dir output/] [--config <overrides.json>]

Or from within the video_pipeline directory:
    python main.py --input <video> --styles real_estate dynamic

Example:
    python -m video_pipeline.main \\
        --input footage/E7_raw.mp4 \\
        --styles real_estate dynamic \\
        --music assets/background.mp3 \\
        --output-dir output/

Each stage logs its progress and decisions to the console. The final output
is one .mp4 file per requested style in the output directory.
"""

import argparse
import json
import logging
import os
import sys
import time
from typing import List, Optional

# ─── Module-level logger (configured after args are parsed) ───────────────────
logger = logging.getLogger("video_pipeline")


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point. Parses args, orchestrates all 8 stages, returns exit code.

    Args:
        argv: Argument list (defaults to sys.argv[1:] if None). Useful for testing.

    Returns:
        0 on success, 1 on fatal error.
    """
    args = _parse_args(argv)
    _configure_logging(args)

    logger.info("=" * 60)
    logger.info("PRAL Video Post-Processing Pipeline v0.1.0")
    logger.info("=" * 60)

    # ── Load config overrides ────────────────────────────────────────────────
    if args.config:
        _apply_config_overrides(args.config)

    # ── Validate config weights sum to 1.0 ──────────────────────────────────
    from . import config as cfg
    _validate_weights(cfg)

    # ── Validate requested styles ────────────────────────────────────────────
    from .styles import AVAILABLE_STYLES
    style_configs = _resolve_styles(args.styles, AVAILABLE_STYLES)

    # ── Validate input file ──────────────────────────────────────────────────
    if not os.path.exists(args.input):
        logger.error("Input file not found: %s", args.input)
        return 1

    t_pipeline_start = time.time()

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 1 — Ingest
    # ─────────────────────────────────────────────────────────────────────────
    _stage_header("Stage 1 — Ingest")
    from .ingest import ingest
    try:
        video = ingest(args.input)
    except (FileNotFoundError, ValueError) as exc:
        logger.error("Ingest failed: %s", exc)
        return 1

    logger.info(
        "Source: %s | %.1fs @ %.2f fps | %d×%d | codec=%s | %d analysis frames",
        os.path.basename(args.input),
        video.duration, video.fps,
        video.width, video.height,
        video.codec,
        len(video.analysis_frames),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 2 — Segmentation
    # ─────────────────────────────────────────────────────────────────────────
    _stage_header("Stage 2 — Segmentation")
    from .segmenter import segment

    # Check if any requested style needs bypass_duration_guards.
    # We run one segmentation pass; bypass is handled per-style in the selector.
    # (All styles share the same candidate pool from a single segmentation.)
    clips = segment(video, bypass_duration_guards=False)

    if not clips:
        logger.error(
            "Segmentation produced no clips. "
            "The video may be too short or have too few sampled frames."
        )
        return 1

    logger.info("Segmentation produced %d candidate clips", len(clips))

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 3 — Scoring
    # ─────────────────────────────────────────────────────────────────────────
    _stage_header("Stage 3 — Scoring")
    from .scorer import score_all_clips
    t_score = time.time()
    clips = score_all_clips(clips)
    logger.info("Scoring complete in %.1fs", time.time() - t_score)

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 4 — Ranking
    # ─────────────────────────────────────────────────────────────────────────
    _stage_header("Stage 4 — Ranking")
    from .ranker import rank
    try:
        ranked = rank(clips)
    except ValueError as exc:
        logger.error("Ranking configuration error: %s", exc)
        return 1

    if not ranked:
        logger.error(
            "All clips failed the quality filter. "
            "Check if footage is well-lit (sharpness threshold: %.1f) "
            "and not overly shaky (smoothness threshold: %.2f). "
            "Lower these thresholds in config.py or with --config overrides.",
            cfg.MIN_SHARPNESS, cfg.MIN_SMOOTHNESS,
        )
        return 1

    logger.info(
        "%d clips survived hard filter (%.0f%% pass rate)",
        len(ranked),
        100 * len(ranked) / len(clips),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Stage 5 — Diversity Filtering
    # ─────────────────────────────────────────────────────────────────────────
    _stage_header("Stage 5 — Diversity Filtering")
    from .diversity import build_curated_pool
    curated_pool = build_curated_pool(ranked)

    if not curated_pool:
        logger.error("Diversity filtering produced an empty pool. Cannot continue.")
        return 1

    logger.info(
        "Curated pool: %d clips (from %d ranked survivors)",
        len(curated_pool), len(ranked),
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Stages 6, 7, 8 — Per-style selection and assembly
    # ─────────────────────────────────────────────────────────────────────────
    os.makedirs(args.output_dir, exist_ok=True)
    outputs = []
    errors = []

    for style in style_configs:
        _stage_header(f"Style: {style.name}")

        # Stage 7 — Selection
        from .selector import select_clips
        selected = select_clips(curated_pool, style)

        if not selected:
            logger.warning(
                "Style '%s': no clips selected; skipping assembly",
                style.name,
            )
            errors.append(style.name)
            continue

        # Stage 8 — Assembly
        from .assembler import assemble
        try:
            output_path = assemble(
                clips=selected,
                style=style,
                source_path=args.input,
                output_dir=args.output_dir,
                music_path=args.music,
            )
            outputs.append((style.name, output_path))
        except (ValueError, RuntimeError) as exc:
            logger.error("Assembly failed for style '%s': %s", style.name, exc)
            errors.append(style.name)
            continue

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    total_elapsed = time.time() - t_pipeline_start
    _stage_header("Complete")
    logger.info("Pipeline finished in %.1fs", total_elapsed)

    if outputs:
        logger.info("Outputs:")
        for style_name, path in outputs:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            logger.info("  %-20s → %s (%.1f MB)", style_name, path, size_mb)

    if errors:
        logger.warning("Styles that failed or produced no output: %s", ", ".join(errors))

    if not outputs:
        logger.error("No output files were produced.")
        return 1

    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    """Parse and return command-line arguments.

    Args:
        argv: Argument list, or None to read from sys.argv.

    Returns:
        Parsed Namespace.
    """
    from .styles import AVAILABLE_STYLES

    parser = argparse.ArgumentParser(
        prog="video_pipeline",
        description=(
            "PRAL Video Post-Processing Pipeline — "
            "turn raw drone footage into polished highlight videos."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Available styles:\n"
            + "\n".join(f"  {name}" for name in AVAILABLE_STYLES)
            + "\n\nExample:\n"
            "  python -m video_pipeline.main --input footage/E7.mp4 "
            "--styles real_estate dynamic --output-dir output/"
        ),
    )

    parser.add_argument(
        "--input", "-i",
        required=True,
        metavar="VIDEO",
        help="Path to raw source video file.",
    )
    parser.add_argument(
        "--styles", "-s",
        required=True,
        nargs="+",
        metavar="STYLE",
        help=(
            "One or more style names to render. "
            f"Choices: {', '.join(AVAILABLE_STYLES)}"
        ),
    )
    parser.add_argument(
        "--music", "-m",
        default=None,
        metavar="AUDIO",
        help="Optional path to audio file for background music.",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output",
        metavar="DIR",
        help="Directory for rendered .mp4 files. Created if it does not exist. (default: output/)",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        metavar="JSON",
        help=(
            "Optional path to a JSON file with config.py overrides. "
            "Keys must match constants in config.py (e.g. {\"MIN_SHARPNESS\": 30.0})."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging (very verbose).",
    )

    return parser.parse_args(argv)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _configure_logging(args: argparse.Namespace) -> None:
    """Set up the root logger with a human-readable format.

    At INFO level, the format is:  HH:MM:SS [stage] message
    At DEBUG level, the file and line are included.

    Args:
        args: Parsed arguments (reads args.verbose).
    """
    level = logging.DEBUG if args.verbose else logging.INFO
    fmt = "%(asctime)s  %(message)s"
    datefmt = "%H:%M:%S"

    logging.basicConfig(level=level, format=fmt, datefmt=datefmt, stream=sys.stdout)

    # Suppress moviepy's own verbose output (it goes through a custom logger)
    logging.getLogger("moviepy").setLevel(logging.WARNING)
    logging.getLogger("imageio").setLevel(logging.WARNING)


def _apply_config_overrides(config_path: str) -> None:
    """Override constants in config.py from a JSON file.

    The JSON file should be a flat dict mapping config constant names to
    new values, e.g.:
        {"MIN_SHARPNESS": 30.0, "MIN_SMOOTHNESS": 0.5, "MAX_POOL_SIZE": 30}

    Args:
        config_path: Path to the JSON override file.
    """
    from . import config as cfg

    if not os.path.exists(config_path):
        logger.error("Config override file not found: %s", config_path)
        sys.exit(1)

    try:
        with open(config_path) as f:
            overrides = json.load(f)
    except (json.JSONDecodeError, IOError) as exc:
        logger.error("Could not parse config override file: %s", exc)
        sys.exit(1)

    applied = []
    unknown = []
    for key, value in overrides.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
            applied.append(f"{key}={value!r}")
        else:
            unknown.append(key)

    if applied:
        logger.info("Config overrides applied: %s", ", ".join(applied))
    if unknown:
        logger.warning(
            "Unknown config keys (ignored): %s. "
            "Check that these match constants in config.py",
            ", ".join(unknown),
        )


def _validate_weights(cfg) -> None:
    """Confirm that the four scoring weights sum to 1.0.

    Args:
        cfg: The config module.

    Raises:
        SystemExit: If the weights don't sum to 1.0 (exits with code 1).
    """
    total = (
        cfg.WEIGHT_SHARPNESS
        + cfg.WEIGHT_SMOOTHNESS
        + cfg.WEIGHT_COMPOSITION
        + cfg.WEIGHT_EXPOSURE
    )
    if abs(total - 1.0) > 1e-4:
        logger.error(
            "Scoring weights in config.py must sum to 1.0, but sum is %.6f. "
            "Adjust WEIGHT_SHARPNESS (%.2f), WEIGHT_SMOOTHNESS (%.2f), "
            "WEIGHT_COMPOSITION (%.2f), WEIGHT_EXPOSURE (%.2f).",
            total,
            cfg.WEIGHT_SHARPNESS, cfg.WEIGHT_SMOOTHNESS,
            cfg.WEIGHT_COMPOSITION, cfg.WEIGHT_EXPOSURE,
        )
        sys.exit(1)


def _resolve_styles(names: List[str], registry: dict) -> list:
    """Look up style names in the registry and return the StyleConfig objects.

    Args:
        names: List of style name strings from the CLI.
        registry: AVAILABLE_STYLES dict from styles.py.

    Returns:
        List of StyleConfig objects in the order the user specified.

    Raises:
        SystemExit: If any name is not found in the registry.
    """
    valid_names = sorted(registry.keys())
    resolved = []
    errors = []

    for name in names:
        if name in registry:
            resolved.append(registry[name])
        else:
            errors.append(name)

    if errors:
        logger.error(
            "Unknown style(s): %s\n"
            "Valid styles are: %s",
            ", ".join(errors),
            ", ".join(valid_names),
        )
        sys.exit(1)

    return resolved


def _stage_header(title: str) -> None:
    """Print a visible section header for a pipeline stage.

    Args:
        title: Stage name or description.
    """
    logger.info("")
    logger.info("── %s %s", title, "─" * max(0, 50 - len(title)))


if __name__ == "__main__":
    sys.exit(main())
