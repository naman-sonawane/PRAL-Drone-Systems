"""
Stage 8 — Assembly

Renders the final video for each style. For each selected clip:
  - Extracts the exact time range from the full-resolution source
  - Applies the style's color grade via moviepy's fl_image
  - Resizes/crops to the output resolution
  - Stitches clips with the appropriate transition (crossfade or hard cut)
  - Optionally mixes in a background music track
  - Exports a finished .mp4 file

Color grading is applied in this order: brightness → contrast → saturation → warmth.
Order matters because the operations interact: applying brightness before contrast
means contrast centers on the brightened values, which is more predictable.

NOTE on moviepy frame format: moviepy passes frames to fl_image as RGB, not BGR.
Warmth adjustments (R +warmth, B -warmth) use RGB channel indices [0] and [2].
The cv2.cvtColor calls in saturation processing use COLOR_RGB2HSV and COLOR_HSV2RGB.
"""

import logging
import os
from typing import List, Optional

import cv2
import numpy as np

from . import config
from .segmenter import CandidateClip
from .styles import StyleConfig

logger = logging.getLogger(__name__)

# Social vertical output resolution (1080×1920 for TikTok/Reels/Shorts)
_VERTICAL_RESOLUTION = (1080, 1920)


def assemble(
    clips: List[CandidateClip],
    style: StyleConfig,
    source_path: str,
    output_dir: str,
    music_path: Optional[str] = None,
) -> str:
    """Render a finished video for one style from a list of selected clips.

    Imports moviepy lazily to keep startup time fast when only stages 1-7
    are being inspected or tested.

    Args:
        clips: Ordered list of CandidateClips from Stage 7 (selector.py).
        style: StyleConfig defining color grade, transitions, and output params.
        source_path: Path to the original full-resolution source video.
        output_dir: Directory where the rendered mp4 will be written.
        music_path: Optional path to an audio file for background music.

    Returns:
        Absolute path to the rendered mp4 file.

    Raises:
        ValueError: If clips is empty or too many clips fail to load.
        RuntimeError: If moviepy cannot write the output file.
    """
    if not clips:
        raise ValueError(f"No clips provided for style '{style.name}'")

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{style.output_suffix}.mp4")

    logger.info(
        "Assembling style '%s': %d clips → %s",
        style.name, len(clips), output_path,
    )

    # Lazy import — moviepy is slow to import; only load when actually rendering
    try:
        from moviepy.editor import (
            VideoFileClip,
            AudioFileClip,
            concatenate_videoclips,
            CompositeVideoClip,
            ColorClip,
        )
    except ImportError as exc:
        raise RuntimeError(
            "moviepy is required for assembly. Install with: pip install moviepy"
        ) from exc

    # Step 1 & 2 & 3: Extract clips, apply color grade, resize/crop
    processed_clips = []
    failed_count = 0

    for clip in clips:
        rendered = _render_clip(clip, style, source_path, VideoFileClip)
        if rendered is None:
            failed_count += 1
            continue
        processed_clips.append(rendered)

    # Check failure threshold
    failure_rate = failed_count / len(clips)
    if failure_rate > config.MAX_CLIP_LOAD_FAILURES:
        raise ValueError(
            f"Style '{style.name}': {failed_count}/{len(clips)} clips failed to load "
            f"({failure_rate:.0%} > MAX_CLIP_LOAD_FAILURES {config.MAX_CLIP_LOAD_FAILURES:.0%}). "
            "Check that the source video file is accessible and not corrupted."
        )

    if not processed_clips:
        raise ValueError(
            f"Style '{style.name}': all clips failed to load; no output produced."
        )

    if failed_count > 0:
        logger.warning(
            "Style '%s': %d clips failed to load and were skipped",
            style.name, failed_count,
        )

    # Step 4: Stitch clips with the appropriate transition
    final_video = _stitch_clips(processed_clips, style)

    # Step 5: Add music if provided
    if music_path is not None:
        final_video = _add_music(final_video, music_path, AudioFileClip)

    # Step 6: Export
    try:
        logger.info("Writing '%s' (%.1fs) ...", output_path, final_video.duration)
        final_video.write_videofile(
            output_path,
            codec="libx264",
            audio_codec="aac",
            fps=config.OUTPUT_FPS,
            threads=4,
            logger=None,  # suppress moviepy's own progress bar in favor of our logging
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to write video for style '{style.name}': {exc}"
        ) from exc
    finally:
        # Always close all clips to release file handles, even on failure
        final_video.close()
        for c in processed_clips:
            try:
                c.close()
            except Exception:
                pass

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    logger.info(
        "Style '%s' complete: %s (%.1f MB)",
        style.name, output_path, file_size_mb,
    )
    return output_path


def _render_clip(
    clip: CandidateClip,
    style: StyleConfig,
    source_path: str,
    VideoFileClip,  # injected to avoid re-import
) -> Optional[object]:  # returns moviepy VideoClip or None
    """Extract, grade, and resize a single clip.

    Args:
        clip: CandidateClip with start_time and end_time set. end_time may
            have been truncated by selector.py for styles like timelapse_feel.
        style: Style config for color grade and aspect ratio.
        source_path: Path to the full-resolution source video.
        VideoFileClip: moviepy class (injected for lazy import).

    Returns:
        A moviepy VideoClip ready for stitching, or None if loading failed.
    """
    try:
        logger.debug(
            "Loading clip %d: %.1f–%.1fs from %s",
            clip.clip_id, clip.start_time, clip.end_time, source_path,
        )
        video_clip = VideoFileClip(source_path).subclip(clip.start_time, clip.end_time)
    except Exception as exc:
        logger.error(
            "Failed to load clip %d [%.1f–%.1fs]: %s",
            clip.clip_id, clip.start_time, clip.end_time, exc,
        )
        return None

    # Build the color grading function (closes over style.color_grade)
    grader = _make_frame_grader(style.color_grade)
    graded_clip = video_clip.fl_image(grader)

    # Resize / crop to target output resolution
    resized_clip = _resize_clip(graded_clip, style)

    return resized_clip


def _make_frame_grader(grade_config: dict):
    """Return a frame-level function that applies a color grade.

    The returned function is intended for moviepy's fl_image(). It takes
    an RGB uint8 frame (H, W, 3) and returns a graded RGB uint8 frame.

    Operations are applied in this order:
      1. Brightness — multiply all channels
      2. Contrast  — scale around 127.5 midpoint
      3. Saturation — scale the S channel in HSV
      4. Warmth    — shift R up, B down (RGB channel order from moviepy)

    Args:
        grade_config: Dict with keys brightness, contrast, saturation, warmth.

    Returns:
        Callable(frame: ndarray) → ndarray suitable for fl_image.
    """
    brightness  = float(grade_config.get("brightness",  1.0))
    contrast    = float(grade_config.get("contrast",    1.0))
    saturation  = float(grade_config.get("saturation",  1.0))
    warmth      = float(grade_config.get("warmth",      0.0))

    def grade_frame(frame: np.ndarray) -> np.ndarray:
        """Apply color grade to a single RGB frame from moviepy."""
        result = frame.astype(np.float32)

        # 1. Brightness
        if brightness != 1.0:
            result *= brightness

        # 2. Contrast — scale around the 127.5 midpoint
        if contrast != 1.0:
            result = (result - 127.5) * contrast + 127.5

        # 3. Saturation — convert to HSV, scale S, convert back
        # moviepy uses RGB; cv2 HSV from RGB uses COLOR_RGB2HSV
        if saturation != 1.0:
            clipped = np.clip(result, 0, 255).astype(np.uint8)
            hsv = cv2.cvtColor(clipped, cv2.COLOR_RGB2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
            result = cv2.cvtColor(
                np.clip(hsv, 0, 255).astype(np.uint8),
                cv2.COLOR_HSV2RGB,
            ).astype(np.float32)

        # 4. Warmth — add to R channel (index 0), subtract from B channel (index 2)
        # warmth=+0.06 means add 0.06*255 ≈ 15 to R and subtract 15 from B
        if warmth != 0.0:
            shift = warmth * 255.0
            result[:, :, 0] += shift   # R up
            result[:, :, 2] -= shift   # B down

        return np.clip(result, 0, 255).astype(np.uint8)

    return grade_frame


def _resize_clip(clip, style: StyleConfig):
    """Resize or crop a clip to the style's output resolution.

    Handles three cases:
      - "16:9" (default): resize to OUTPUT_RESOLUTION (1920×1080), letterboxing
        if the source has a different aspect ratio.
      - "9:16" (social_vertical): center-crop to a 9:16 strip then resize to
        1080×1920.
      - cinematic with letterbox=True: resize to 1920×1080 then add black bars
        to achieve 2.35:1 (827 lines of content within 1080 lines of output).

    Args:
        clip: moviepy VideoClip with a color grade already applied.
        style: Style config with output_aspect_ratio and letterbox fields.

    Returns:
        Resized/cropped moviepy VideoClip.
    """
    if style.output_aspect_ratio == "9:16":
        return _crop_to_vertical(clip)
    else:
        target_w, target_h = config.OUTPUT_RESOLUTION
        resized = clip.resize((target_w, target_h))

        # STRETCH_GOAL_LETTERBOX: add 2.35:1 black bars for cinematic style
        if style.letterbox:
            resized = _apply_letterbox(resized, target_w, target_h)

        return resized


def _crop_to_vertical(clip):
    """Center-crop a 16:9 clip to 9:16 and resize to 1080×1920.

    The crop takes the center vertical strip of the frame that has 9:16
    aspect ratio, preserving the horizontal center of the shot (which is
    where the subject usually is in drone footage aimed at a building).

    Args:
        clip: moviepy VideoClip at native resolution.

    Returns:
        moviepy VideoClip at 1080×1920 (9:16).
    """
    # Calculate the width of a 9:16 strip that fits in the full-height frame.
    # Source height: H, desired crop width: H * 9/16
    # Center x offset: (W - crop_width) / 2
    source_w = clip.w
    source_h = clip.h
    crop_w = int(source_h * 9 / 16)
    x_center = source_w // 2

    # Use moviepy's crop (x_center, y_center, width, height)
    cropped = clip.crop(
        x_center=x_center,
        y_center=source_h // 2,
        width=crop_w,
        height=source_h,
    )

    out_w, out_h = _VERTICAL_RESOLUTION
    return cropped.resize((out_w, out_h))


def _apply_letterbox(clip, target_w: int, target_h: int):
    """Add black bars to achieve 2.35:1 aspect ratio within 16:9 output.

    Crops the clip vertically to 2.35:1 content area, then pads to
    target_h with black bars (the padding is handled via clip positioning
    on a black ColorClip).

    2.35:1 within 1920×1080: content height = 1920 / 2.35 ≈ 817 pixels.
    Black bars: (1080 - 817) / 2 ≈ 132 pixels top and bottom.

    STRETCH_GOAL_LETTERBOX: This is a stretch goal. Enabled by cinematic
    style's letterbox=True flag.

    Args:
        clip: moviepy VideoClip at target_w × target_h.
        target_w: Output width in pixels.
        target_h: Output height in pixels.

    Returns:
        moviepy VideoClip with letterbox applied.
    """
    try:
        from moviepy.editor import CompositeVideoClip, ColorClip

        content_h = int(target_w / 2.35)
        y_offset = (target_h - content_h) // 2

        # Crop the clip to the 2.35:1 content area
        cropped = clip.crop(y1=y_offset, y2=y_offset + content_h)
        # Reposition on a black background
        cropped = cropped.set_position(("center", y_offset))
        black_bg = ColorClip(
            size=(target_w, target_h),
            color=(0, 0, 0),
            duration=clip.duration,
        )
        return CompositeVideoClip([black_bg, cropped])

    except Exception as exc:
        logger.warning("Letterbox application failed (%s); skipping", exc)
        return clip


def _stitch_clips(processed_clips: List, style: StyleConfig):
    """Stitch a list of processed moviepy clips using the style's transition type.

    Args:
        processed_clips: List of moviepy VideoClips (graded, resized).
        style: Style config with transition_type and transition_duration.

    Returns:
        A single moviepy VideoClip representing the full stitched video.

    Raises:
        ValueError: If transition_type is unrecognized.
    """
    from moviepy.editor import concatenate_videoclips

    if len(processed_clips) == 1 or style.transition_type in ("hard_cut", "none"):
        # Hard cuts and single-clip outputs are a simple concatenation
        return concatenate_videoclips(processed_clips, method="compose")

    elif style.transition_type == "crossfade":
        dur = style.transition_duration
        if dur <= 0:
            return concatenate_videoclips(processed_clips, method="compose")

        # Apply crossfadein to every clip after the first.
        # concatenate_videoclips with padding=-dur causes the clips to overlap
        # by dur seconds, and the crossfadein/crossfadeout produce the blend.
        clips_with_fade = [processed_clips[0]]
        for clip in processed_clips[1:]:
            clips_with_fade.append(clip.crossfadein(dur))

        return concatenate_videoclips(
            clips_with_fade,
            padding=-dur,
            method="compose",
        )

    else:
        logger.warning(
            "Unknown transition_type '%s' for style '%s'; falling back to hard_cut",
            style.transition_type, style.name,
        )
        return concatenate_videoclips(processed_clips, method="compose")


def _add_music(video_clip, music_path: str, AudioFileClip) -> object:
    """Attach a background music track to the video clip.

    Loops the track if it is shorter than the video; trims if longer.
    Sets volume to config.MUSIC_VOLUME.

    STRETCH_GOAL_BEAT_SYNC: For styles with music_tempo_preference="fast",
    the correct implementation uses librosa.beat.beat_track() to extract
    beat timestamps and passes them to selector.py so clip cut points snap
    to beats. That integration is not implemented here — this function only
    handles the simpler "attach and loop" use case.

    Args:
        video_clip: A moviepy VideoClip (the stitched video without audio).
        music_path: Path to an audio file (mp3, wav, aac, etc.).
        AudioFileClip: moviepy class (injected for lazy import).

    Returns:
        The video clip with audio attached.
    """
    if not os.path.exists(music_path):
        logger.warning("Music file not found: %s; skipping audio", music_path)
        return video_clip

    try:
        audio = AudioFileClip(music_path)

        # Loop if music is shorter than video
        if audio.duration < video_clip.duration:
            audio = audio.audio_loop(duration=video_clip.duration)
        else:
            audio = audio.subclip(0, video_clip.duration)

        audio = audio.volumex(config.MUSIC_VOLUME)
        return video_clip.set_audio(audio)

    except Exception as exc:
        logger.warning("Failed to add music (%s); continuing without audio", exc)
        return video_clip
