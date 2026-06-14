"""
stage4_mock_data.py

Computes geometry-based interest scores for Stage 4: Interest Field & Value Assignment.

Loads the existing building mesh (pipeline/data/building_mesh.ply) and assigns
per-vertex interest scores based on four geometric signals (25% each):

  1. Edge score     -- angular deviation between adjacent face normals at each vertex.
                       High = sharp crease / edge.
  2. Crevice score  -- discrete mean curvature (cotangent Laplacian) signed by
                       concavity. High = inward-curving / crevice area.
  3. Extrusion score -- positive mean curvature. High = convex protrusions that
                        stick out from the main body.
  4. Entrance score  -- Gaussian falloff from bottom-front-center of the mesh.
                        High = near the ground-level front face (entrance area).

Final score = 0.25 * (edge + crevice + extrusion + entrance)  (all normalised to [0,1])

Produces:
  - pipeline/data/interest_scores.npy   -- per-vertex float32 interest scores in [0,1]
  - stage4/interest_scores.npy          -- same copy for legacy consumers

Run:
    python pipeline/stage4_mock_data.py
"""

import os
import numpy as np
import open3d as o3d

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR    = os.path.join(SCRIPT_DIR, "data")
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)

MESH_PATH      = os.path.join(DATA_DIR, "building_mesh.ply")
SCORES_PATH    = os.path.join(DATA_DIR, "interest_scores.npy")
SCORES_PATH_S4 = os.path.join(PROJECT_DIR, "stage4", "interest_scores.npy")

# ---------------------------------------------------------------------------
# Load mesh
# ---------------------------------------------------------------------------
mesh = o3d.io.read_triangle_mesh(MESH_PATH)
mesh.compute_triangle_normals()
mesh.compute_vertex_normals()

V = np.asarray(mesh.vertices,        dtype=np.float64)   # (N, 3)
F = np.asarray(mesh.triangles,       dtype=np.int32)     # (M, 3)
TN = np.asarray(mesh.triangle_normals, dtype=np.float64) # (M, 3)
VN = np.asarray(mesh.vertex_normals,   dtype=np.float64) # (N, 3)

N = len(V)

# ---------------------------------------------------------------------------
# Build adjacency: vertex -> list of incident triangle indices
# ---------------------------------------------------------------------------
v2tri = [[] for _ in range(N)]
for ti, (a, b, c) in enumerate(F):
    v2tri[a].append(ti)
    v2tri[b].append(ti)
    v2tri[c].append(ti)

# ---------------------------------------------------------------------------
# Signal 1: Edge score
# Mean pairwise angular deviation of adjacent face normals, normalised to [0,1].
# A vertex at a sharp crease has incident faces pointing in very different
# directions → high angular spread → high edge score.
# ---------------------------------------------------------------------------
edge_raw = np.zeros(N, dtype=np.float64)

for vi in range(N):
    tris = v2tri[vi]
    if len(tris) < 2:
        edge_raw[vi] = 0.0
        continue
    normals = TN[tris]                          # (k, 3)
    # Pairwise dot products (clipped for arccos stability)
    dots = np.clip(normals @ normals.T, -1.0, 1.0)
    angles = np.arccos(dots)                    # (k, k)
    # Upper-triangle only (avoid double counting)
    k = len(tris)
    mask = np.triu(np.ones((k, k), dtype=bool), k=1)
    edge_raw[vi] = angles[mask].mean() if mask.any() else 0.0

# Normalise to [0, 1]  (max possible angle = π)
edge_score = edge_raw / np.pi

# ---------------------------------------------------------------------------
# Signal 2: Crevice score (discrete cotangent Laplacian mean curvature)
# For each vertex v, iterate over 1-ring triangles. Each triangle (v, v_j, v_k)
# contributes cotangent-weighted edge vectors. The resulting vector H(v) is the
# mean curvature normal; its sign relative to the vertex normal distinguishes
# concave (crevice) from convex regions.
# ---------------------------------------------------------------------------
def safe_cot(a, b):
    """Cotangent of the angle between vectors a and b."""
    dot   = np.dot(a, b)
    cross = np.linalg.norm(np.cross(a, b))
    if cross < 1e-12:
        return 0.0
    return dot / cross


H_vec = np.zeros((N, 3), dtype=np.float64)

for vi in range(N):
    area_sum = 0.0
    for ti in v2tri[vi]:
        tri = F[ti]
        # Identify the other two vertices in this triangle
        others = [idx for idx in tri if idx != vi]
        if len(others) != 2:
            continue
        vj, vk = others[0], others[1]

        p  = V[vi]
        pj = V[vj]
        pk = V[vk]

        # Angle at vj (opposite to edge vi-vk)
        cot_j = safe_cot(p - pj, pk - pj)
        # Angle at vk (opposite to edge vi-vj)
        cot_k = safe_cot(p - pk, pj - pk)

        # Standard cotangent formula: cot_k weights edge (vi→vj), cot_j weights edge (vi→vk)
        H_vec[vi] += cot_k * (pj - p) + cot_j * (pk - p)

        # Voronoi / mixed area (use triangle area / 3 as simple approximation)
        area_sum += np.linalg.norm(np.cross(pj - p, pk - p)) * 0.5

    if area_sum > 1e-12:
        H_vec[vi] /= (2.0 * area_sum)

# Signed curvature: negative dot with outward normal → concave → crevice
signed_curv = -np.einsum("ij,ij->i", H_vec, VN)   # (N,)

# Only keep concave (positive signed_curv after negation)
crevice_raw = np.clip(signed_curv, 0.0, None)

# Normalise
c_max = crevice_raw.max()
crevice_score = crevice_raw / c_max if c_max > 1e-12 else crevice_raw

# ---------------------------------------------------------------------------
# Signal 3: Extrusion score (convex protrusions)
# Reuse H_vec from above. Convex regions have the curvature vector pointing in
# the same direction as the outward vertex normal → positive dot product.
# ---------------------------------------------------------------------------
convex_raw = np.clip(np.einsum("ij,ij->i", H_vec, VN), 0.0, None)

e_max = convex_raw.max()
extrusion_score = convex_raw / e_max if e_max > 1e-12 else convex_raw

# ---------------------------------------------------------------------------
# Signal 4: Entrance score (Gaussian hotspot at bottom-front-center)
# Bottom = Z_min, Front = Y_min, Center = mean X.
# ---------------------------------------------------------------------------
entrance_target = np.array([V[:, 0].mean(), V[:, 1].min(), V[:, 2].min()])
entrance_sigma  = 40_000.0
dists_entrance  = np.linalg.norm(V - entrance_target, axis=1)
entrance_score  = np.exp(-dists_entrance ** 2 / (2.0 * entrance_sigma ** 2))

# ---------------------------------------------------------------------------
# Blend and save
# ---------------------------------------------------------------------------
scores = np.clip(
    0.25 * edge_score + 0.25 * crevice_score + 0.25 * extrusion_score + 0.25 * entrance_score,
    0.0, 1.0,
).astype(np.float32)

np.save(SCORES_PATH, scores)
os.makedirs(os.path.dirname(SCORES_PATH_S4), exist_ok=True)
np.save(SCORES_PATH_S4, scores)

print(f"Vertex count    : {N}")
print(f"Edge score      : min={edge_score.min():.3f}  max={edge_score.max():.3f}  mean={edge_score.mean():.3f}")
print(f"Crevice score   : min={crevice_score.min():.3f}  max={crevice_score.max():.3f}  mean={crevice_score.mean():.3f}")
print(f"Extrusion score : min={extrusion_score.min():.3f}  max={extrusion_score.max():.3f}  mean={extrusion_score.mean():.3f}")
print(f"Entrance score  : min={entrance_score.min():.3f}  max={entrance_score.max():.3f}  mean={entrance_score.mean():.3f}")
print(f"Final scores    : min={scores.min():.3f}  max={scores.max():.3f}  mean={scores.mean():.3f}")
print(f"Scores written  : {SCORES_PATH}")
print(f"                : {SCORES_PATH_S4}")
