"""Open-vocabulary detector -- *interface only* (Stage 1, Test 4 / Tier C).

The real system runs an open-vocabulary detector (YOLO-World / Grounding DINO)
on the ascent/top-down frame with text prompts like ``"building"`` to propose
candidate structures, whose boxes are then reprojected to GPS (see
:mod:`reproject`). That model needs weights and real imagery, so here we define
only the **contract** every detector must satisfy plus a deterministic
:class:`StubDetector` for wiring/orchestration tests. The accuracy KPI
(recall >= 90%, <= 1 FP/scene) is Test 4, a Tier-C test that is written against
this interface but skipped until field data exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np


@dataclass(frozen=True)
class Detection:
    """A single open-vocabulary detection.

    ``box_xyxy`` is ``[x0, y0, x1, y1]`` in image pixels, ``score`` a confidence
    in ``[0, 1]``, and ``label`` the matched text prompt (e.g. ``"building"``).
    """

    box_xyxy: np.ndarray
    score: float
    label: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "box_xyxy", np.asarray(self.box_xyxy, dtype=float).reshape(4)
        )

    @property
    def center(self) -> np.ndarray:
        """Box center pixel ``(u, v)``."""
        b = self.box_xyxy
        return np.array([0.5 * (b[0] + b[2]), 0.5 * (b[1] + b[3])])


class OpenVocabDetector(Protocol):
    """Interface a real open-vocabulary detector must implement.

    Implementations take an image (``H x W x 3`` array) and a list of text
    prompts and return scored boxes. The pipeline depends only on this Protocol,
    never on a concrete model, so the heavy model is swappable and the rest of
    Stage 1 stays testable without it.
    """

    def detect(
        self, image: np.ndarray, prompts: Sequence[str], score_threshold: float = ...
    ) -> list[Detection]:
        ...


@dataclass
class StubDetector:
    """Deterministic stand-in for the real detector (no model, no imagery).

    It ignores pixels and replays a fixed list of :class:`Detection` objects,
    filtered by ``score_threshold`` and by whether their label is in ``prompts``.
    This lets orchestration / reprojection tests run end-to-end deterministically
    while the real model is decorated as Tier C.
    """

    detections: list[Detection]

    def detect(
        self,
        image: np.ndarray,
        prompts: Sequence[str],
        score_threshold: float = 0.3,
    ) -> list[Detection]:
        wanted = {p.lower() for p in prompts}
        return [
            d
            for d in self.detections
            if d.score >= score_threshold and d.label.lower() in wanted
        ]
