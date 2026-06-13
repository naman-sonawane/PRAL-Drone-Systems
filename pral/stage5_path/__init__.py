"""Stage 5 -- Path Optimization & Variety Shots.

Given a Stage-4 :class:`~pral.core.schemas.ValueField` and a Stage-2
:class:`~pral.core.schemas.ObstacleMap`, this stage:

1. **Selects viewpoints** -- local maxima of the value field, filtered so every
   kept viewpoint is inside the geofence *and* clears the obstacle map
   (:mod:`pral.stage5_path.viewpoints`, Test 19).
2. **Orders them** -- an OR-Tools TSP over the selected viewpoints, provably
   close to the brute-force optimum on small sets
   (:mod:`pral.stage5_path.routing`, Test 20).
3. **Draws a smooth trajectory** -- a time-parameterised C2 spline through the
   ordered viewpoints that respects v_max / a_max / jerk limits and keeps
   clearance >= the safety margin everywhere
   (:mod:`pral.stage5_path.trajectory`, Test 21).
4. **Assigns shot variety** -- maps subjects to a shot-grammar library with a
   no-two-adjacent-same constraint (:mod:`pral.stage5_path.grammar`, Test 22).
5. **Emits a mission** -- assembles a :class:`~pral.core.schemas.Mission` plus a
   :class:`~pral.core.schemas.CuratedFootageSet` that loads and flies clean in
   the kinematic sim (:mod:`pral.stage5_path.mission`, Test 23).
"""

from pral.stage5_path import grammar, mission, routing, trajectory, viewpoints

__all__ = ["viewpoints", "routing", "trajectory", "grammar", "mission"]
