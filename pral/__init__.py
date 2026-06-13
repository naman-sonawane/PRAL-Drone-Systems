"""PRAL drone footage-acquisition pipeline.

Lightweight, deterministic Python implementation of the footage-acquisition
pipeline. The :mod:`pral.core` subpackage is the shared backbone every stage
imports: coordinate frames, the pinhole camera model, and the data contracts
(pydantic models + JSON Schemas) that flow between stages.
"""

__version__ = "0.1.0"
