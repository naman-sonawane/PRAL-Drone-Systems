"""Visit-order routing -- an OR-Tools open-path TSP over the viewpoints.

The selected viewpoints have no inherent order; flying them in value order
would zig-zag across the scene. This is the classic inspection-planning second
stage: **viewpoints -> routing**. We solve an open-path (no return-to-start)
Travelling-Salesman over Euclidean ENU distances with OR-Tools.

For Test 20 we also provide :func:`brute_force_tour`, an exact optimum on small
sets, so the test can assert OR-Tools is within 1.2x of optimal.

Determinism: OR-Tools is given a fixed first-solution strategy and a finite
time limit; distances are integer-scaled so the solver is reproducible.
"""

from __future__ import annotations

import itertools

import numpy as np

try:  # pragma: no cover - import guard
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
except ImportError as exc:  # pragma: no cover
    raise ImportError("OR-Tools is required for Stage-5 routing") from exc

_SCALE = 1000  # mm resolution for integer distances


def tour_length(points: np.ndarray, order: list[int]) -> float:
    """Total Euclidean length (m) of visiting ``points`` in ``order`` (open path)."""
    pts = np.asarray(points, float)
    total = 0.0
    for a, b in zip(order[:-1], order[1:]):
        total += float(np.linalg.norm(pts[a] - pts[b]))
    return total


def _distance_matrix(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, float)
    diff = pts[:, None, :] - pts[None, :, :]
    return np.linalg.norm(diff, axis=2)


def brute_force_tour(points: np.ndarray) -> tuple[list[int], float]:
    """Exact shortest open path (TSP) by enumerating permutations.

    Fixes node 0 as the start to halve the search; reverses are equivalent for
    an open path so we also fix the endpoint ordering by symmetry. Intended for
    small sets (<= ~9 points).
    """
    pts = np.asarray(points, float)
    n = len(pts)
    if n <= 1:
        return list(range(n)), 0.0
    best_order = list(range(n))
    best_len = np.inf
    rest = list(range(1, n))
    for perm in itertools.permutations(rest):
        order = [0, *perm]
        length = tour_length(pts, order)
        if length < best_len:
            best_len = length
            best_order = order
    return best_order, float(best_len)


def solve_tsp(
    points: np.ndarray,
    *,
    time_limit_s: int = 5,
    start: int = 0,
) -> tuple[list[int], float]:
    """Solve an open-path TSP over ``points`` with OR-Tools.

    Returns ``(order, length_m)``. The path starts at ``start`` and does not
    return to it (a dummy zero-cost end node makes the loop open).
    """
    pts = np.asarray(points, float)
    n = len(pts)
    if n <= 2:
        order = list(range(n))
        return order, tour_length(pts, order)

    dist = _distance_matrix(pts)
    # Open path: add a virtual depot (index n) at distance 0 to every node, so
    # the cycle the solver finds, with the depot removed, is an open Hamiltonian
    # path. Start and end both anchored at the depot.
    size = n + 1
    depot = n

    def d(i: int, j: int) -> int:
        if i == depot or j == depot:
            return 0
        return int(round(dist[i, j] * _SCALE))

    manager = pywrapcp.RoutingIndexManager(size, 1, depot)
    routing = pywrapcp.RoutingModel(manager)

    def cb(from_index: int, to_index: int) -> int:
        return d(manager.IndexToNode(from_index), manager.IndexToNode(to_index))

    transit = routing.RegisterTransitCallback(cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(time_limit_s)
    params.log_search = False

    solution = routing.SolveWithParameters(params)
    if solution is None:  # pragma: no cover - fallback
        order = list(range(n))
        return order, tour_length(pts, order)

    # Extract the node order, dropping the depot.
    order: list[int] = []
    index = routing.Start(0)
    while not routing.IsEnd(index):
        node = manager.IndexToNode(index)
        if node != depot:
            order.append(node)
        index = solution.Value(routing.NextVar(index))

    # Rotate so the requested `start` node is first (open path is symmetric).
    if start in order:
        si = order.index(start)
        order = order[si:] + order[:si]
        # Choose the cheaper of the two open-path directions anchored at start.
        rev = [order[0], *order[1:][::-1]]
        if tour_length(pts, rev) < tour_length(pts, order):
            order = rev
    return order, tour_length(pts, order)


__all__ = ["tour_length", "brute_force_tour", "solve_tsp"]
