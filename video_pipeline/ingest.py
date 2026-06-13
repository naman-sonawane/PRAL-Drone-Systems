"""
Stage 1 — Ingest & Normalize

Reads the raw video file, extracts technical metadata, and prepares a
downscaled analysis copy of frames at regular intervals. Full-resolution
footage is never loaded into memory until Stage 8 — analysis always runs
on ANALYSIS_RESOLUTION frames.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import config

logger = logging.getLogger(__name__)


@dataclass
class IngestedVideo:
    """All metadata and analysis frames for a single source video file.

    Attributes:
        path: Absolute path to the source video file.
        duration: Total duration in seconds.
        fps: Native frame rate of the source.
        width: Native frame width in pixels.
        height: Native frame height in pixels.
        codec: Video codec name (e.g. "h264").
        created_at: Creation timestamp string from file metadata, or None.
        analysis_frames: List of (timestamp_seconds, frame_ndarray) tuples.
            Frames are at config.ANALYSIS_RESOLUTION, dtype uint8, BGR.
    """

    path: str
    duration: float
    fps: float
    width: int
    height: int
    codec: str
    created_at: Optional[str]
    analysis_frames: List[Tuple[float, np.ndarray]] = field(default_factory=list)


def ingest(video_path: str) -> IngestedVideo:
    """Read video metadata and extract analysis frames from a video file.

    Attempts to use ffprobe for metadata first; falls back to OpenCV if
    ffprobe is unavailable or fails. Frame extraction always uses OpenCV.

    Args:
        video_path: Path to the source video file.

    Returns:
        IngestedVideo populated with metadata and analysis frames.

    Raises:
        FileNotFoundError: If the video file does not exist.
        ValueError: If the file is unreadable, has no video stream, or is
            shorter than config.MIN_VIDEO_DURATION.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    logger.info("Ingesting: %s", video_path)

    # Try ffprobe first; fall back to OpenCV if unavailable
    try:
        meta = _read_metadata_ffprobe(video_path)
        logger.info("Metadata via ffprobe: duration=%.1fs, fps=%.2f, %dx%d, codec=%s",
                    meta["duration"], meta["fps"], meta["width"], meta["height"], meta["codec"])
    except (FileNotFoundError, subprocess.SubprocessError, KeyError, ValueError) as exc:
        logger.warning("ffprobe unavailable or failed (%s); falling back to OpenCV", exc)
        meta = _read_metadata_opencv(video_path)
        logger.info("Metadata via OpenCV: duration=%.1fs, fps=%.2f, %dx%d",
                    meta["duration"], meta["fps"], meta["width"], meta["height"])

    if meta["duration"] < config.MIN_VIDEO_DURATION:
        raise ValueError(
            f"Video is too short: {meta['duration']:.1f}s "
            f"(minimum {config.MIN_VIDEO_DURATION}s)"
        )

    logger.info("Extracting analysis frames at %.0f fps → %dx%d ...",
                config.FRAME_SAMPLE_RATE, *config.ANALYSIS_RESOLUTION)

    analysis_frames = _extract_analysis_frames(
        video_path, meta["duration"], meta["fps"]
    )

    logger.info("Extracted %d analysis frames", len(analysis_frames))

    return IngestedVideo(
        path=video_path,
        duration=meta["duration"],
        fps=meta["fps"],
        width=meta["width"],
        height=meta["height"],
        codec=meta["codec"],
        created_at=meta.get("created_at"),
        analysis_frames=analysis_frames,
    )


def _read_metadata_ffprobe(path: str) -> dict:
    """Use ffprobe to read video metadata.

    Args:
        path: Path to the video file.

    Returns:
        Dict with keys: duration (float), fps (float), width (int),
        height (int), codec (str), created_at (Optional[str]).

    Raises:
        FileNotFoundError: If ffprobe is not on the PATH.
        subprocess.SubprocessError: If ffprobe exits with an error.
        ValueError: If the output cannot be parsed or has no video stream.
    """
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    # Find the first video stream
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        raise ValueError("No video stream found in ffprobe output")

    # Parse fps from the r_frame_rate fraction (e.g. "30000/1001")
    fps_str = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    # Duration: prefer stream duration, fall back to format duration
    duration_raw = video_stream.get("duration") or data.get("format", {}).get("duration")
    if duration_raw is None:
        raise ValueError("Could not determine video duration from ffprobe output")
    duration = float(duration_raw)

    # Creation time from format tags
    tags = data.get("format", {}).get("tags", {})
    created_at = tags.get("creation_time") or tags.get("date")

    return {
        "duration": duration,
        "fps": fps,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "codec": video_stream.get("codec_name", "unknown"),
        "created_at": created_at,
    }


def _read_metadata_opencv(path: str) -> dict:
    """Read basic video metadata using OpenCV as a fallback.

    Less accurate than ffprobe (duration can be imprecise with VBR files),
    but works without any external tool.

    Args:
        path: Path to the video file.

    Returns:
        Dict with keys: duration, fps, width, height, codec, created_at.

    Raises:
        ValueError: If OpenCV cannot open the file.
    """
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"OpenCV could not open video file: {path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = frame_count / fps if fps > 0 else 0.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # OpenCV reports a FourCC int; decode to string
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join([chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)]).strip()
    finally:
        cap.release()

    return {
        "duration": duration,
        "fps": fps,
        "width": width,
        "height": height,
        "codec": codec or "unknown",
        "created_at": None,
    }


def _extract_analysis_frames(
    path: str, duration: float, fps: float
) -> List[Tuple[float, np.ndarray]]:
    """Sample frames at config.FRAME_SAMPLE_RATE and downscale to ANALYSIS_RESOLUTION.

    Frames are extracted by seeking to specific timestamps rather than decoding
    every frame, which is much faster for long videos.

    Args:
        path: Path to the video file.
        duration: Video duration in seconds (used to generate timestamps).
        fps: Native frame rate (used to compute frame indices from timestamps).

    Returns:
        List of (timestamp_seconds, frame_ndarray) tuples.
        Frames are dtype uint8, shape (H, W, 3), BGR channel order.
        List is sorted by timestamp ascending.
    """
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        logger.error("Could not open video for frame extraction: %s", path)
        return []

    frames: List[Tuple[float, np.ndarray]] = []
    target_w, target_h = config.ANALYSIS_RESOLUTION
    step = 1.0 / config.FRAME_SAMPLE_RATE  # seconds between samples

    # Generate sample timestamps: 0, step, 2*step, ... up to (duration - step/2)
    timestamps = []
    t = 0.0
    while t < duration:
        timestamps.append(t)
        t += step

    for ts in timestamps:
        # Seek to the timestamp in milliseconds
        cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
        ret, frame = cap.read()
        if not ret or frame is None or frame.size == 0:
            logger.debug("Failed to read frame at t=%.2fs; skipping", ts)
            continue

        # Downscale using INTER_AREA, which is optimal for shrinking
        small = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
        frames.append((ts, small))

    cap.release()

    if not frames:
        logger.error("No frames could be extracted from %s", path)

    return frames
