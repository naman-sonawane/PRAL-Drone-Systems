# PRAL Video Post-Processing Pipeline

Pipeline 2 of the PRAL Drone System — turns raw continuous drone footage into polished, style-specific highlight videos automatically.

## Prerequisites

**System dependencies (must be on PATH):**
```
ffmpeg   # for video encoding/decoding
ffprobe  # for metadata extraction (usually bundled with ffmpeg)
```

**Windows (winget):**
```
winget install ffmpeg
```

**macOS (Homebrew):**
```
brew install ffmpeg
```

**Python packages:**
```
pip install -r requirements.txt
```

## Usage

```
python -m video_pipeline.main \
    --input footage/E7_raw.mp4 \
    --styles real_estate dynamic \
    --music assets/background.mp3 \
    --output-dir output/
```

**Arguments:**

| Argument | Required | Description |
|---|---|---|
| `--input` / `-i` | Yes | Path to raw source video file |
| `--styles` / `-s` | Yes | One or more style names (space-separated) |
| `--music` / `-m` | No | Background audio track (mp3, wav, aac) |
| `--output-dir` / `-o` | No | Output directory (default: `output/`) |
| `--config` / `-c` | No | JSON file of config.py overrides |
| `--verbose` / `-v` | No | Enable DEBUG logging |

## Available styles

| Style | Motion | Clip length | Cuts | Duration |
|---|---|---|---|---|
| `real_estate` | static/slow_pan | 4–8s | crossfade | ~75s |
| `dynamic` | fast/slow_pan | 1–3s | hard cut | ~38s |
| `cinematic` | any | 3–10s | crossfade | ~60s |
| `social_vertical` | fast/slow_pan | 1–4s | hard cut | ~20s (9:16) |
| `walkthrough` | static/slow_pan | 6–12s | crossfade | ~90s |
| `timelapse_feel` | fast | 0.5–1s | hard cut | ~25s |
| `golden_hour` | static/slow_pan | 5–9s | crossfade | ~60s |
| `documentary` | static/slow_pan | 5–8s | hard cut | ~80s |
| `hero_shot` | any | 8–15s | none | 1 clip |
| `overview` | all (static first) | 4–8s | crossfade | ~70s |

## Running tests

```
python -m pytest video_pipeline/tests/ -v
```

## Tuning

All scoring thresholds and weights live in `config.py`. Key values to tune against real footage before the demo:

- `MIN_SHARPNESS` (default 50.0) — lower if too many clips are rejected as blurry
- `MIN_SMOOTHNESS` (default 0.6) — lower if too many clips are rejected as shaky  
- `WEIGHT_*` — four weights (must sum to 1.0) controlling the final clip ranking

You can override any config value without editing the file using `--config overrides.json`:
```json
{
  "MIN_SHARPNESS": 30.0,
  "MIN_SMOOTHNESS": 0.5
}
```

## Project structure

See `prd/VIDEO_PIPELINE_SPEC.md` for the full design document.
