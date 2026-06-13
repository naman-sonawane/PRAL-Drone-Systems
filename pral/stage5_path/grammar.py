"""Shot-grammar variety assignment.

Each subject (a routed viewpoint) gets a cinematographic shot type from the
:class:`~pral.core.schemas.ShotType` library. Variety is a hard constraint:

* **No two adjacent subjects share a grammar** -- consecutive clips must differ.
* **At least ``n_distinct`` distinct grammars** appear across the sequence.

We assign greedily over a fixed, deterministic palette: at each position pick
the highest-priority grammar that differs from the previous one, rotating the
palette start so the distinct-count target is met even on short sequences.
"""

from __future__ import annotations

from pral.core.schemas import ShotType

# Deterministic priority palette. Orbit/flyby/reveal first (the workhorse moves),
# then push-in / top-down / parallax / dronie for variety.
DEFAULT_PALETTE: list[ShotType] = [
    ShotType.ORBIT,
    ShotType.FLYBY,
    ShotType.REVEAL,
    ShotType.PUSH_IN,
    ShotType.TOP_DOWN,
    ShotType.PARALLAX,
    ShotType.DRONIE,
]


def assign_shot_types(
    n_subjects: int,
    *,
    n_distinct: int = 3,
    palette: list[ShotType] | None = None,
) -> list[ShotType]:
    """Assign a shot type per subject with the variety constraints.

    Parameters
    ----------
    n_subjects
        Number of subjects / clips to assign.
    n_distinct
        Minimum number of distinct grammars required across the sequence.
    palette
        Ordered grammar palette to draw from (defaults to
        :data:`DEFAULT_PALETTE`).

    Returns
    -------
    list[ShotType]
        One grammar per subject, no two adjacent equal, with >= min(n_distinct,
        n_subjects, len(palette)) distinct grammars.

    Raises
    ------
    ValueError
        If the palette has fewer than 2 entries (cannot avoid adjacency).
    """
    pal = palette or DEFAULT_PALETTE
    if n_subjects <= 0:
        return []
    if len(pal) < 2:
        raise ValueError("palette needs at least 2 grammars to avoid adjacency")

    # Cycle through the palette: index i -> palette[i % len]. This guarantees
    # adjacent entries differ (len >= 2) and walks distinct grammars as fast as
    # possible, so the first `min(len(pal), n_subjects)` entries are all distinct.
    assigned = [pal[i % len(pal)] for i in range(n_subjects)]

    # Sanity: the cycling scheme already yields max(distinct). If the sequence is
    # long enough, ensure we hit at least n_distinct (true whenever
    # n_subjects >= n_distinct and len(pal) >= n_distinct).
    target = min(n_distinct, n_subjects, len(pal))
    distinct = len(set(assigned))
    if distinct < target:  # pragma: no cover - defensive; cycling guarantees this
        raise ValueError(
            f"could not reach {target} distinct grammars (got {distinct})"
        )
    return assigned


def check_variety(shot_types: list[ShotType], n_distinct: int) -> bool:
    """Validate the diversity constraint on an assigned shot list."""
    if not shot_types:
        return n_distinct <= 0
    for a, b in zip(shot_types[:-1], shot_types[1:]):
        if a == b:
            return False
    return len(set(shot_types)) >= n_distinct


__all__ = ["DEFAULT_PALETTE", "assign_shot_types", "check_variety"]
