"""
PRAL Video Post-Processing Pipeline
Pipeline 2: Autonomous drone footage → polished highlight videos.

Stages:
  1. ingest      — read metadata, downsample frames for analysis
  2. segmenter   — sliding-window candidate clip extraction
  3. scorer      — per-clip quality signals (sharpness, exposure, smoothness, composition)
  4. ranker      — normalize, hard-filter, compute promising_score
  5. diversity   — fingerprint and deduplicate into curated pool
  6. styles      — 10 style template configurations
  7. selector    — style-aware clip selection
  8. assembler   — moviepy render, color grade, transitions, export
"""
__version__ = "0.1.0"
