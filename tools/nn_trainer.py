#!/usr/bin/env python3
"""
Neural-network AI trainer with natural selection.

Uses the game physics (car.step) but only minimal pygame rendering so that
hundreds of cars can be simulated in parallel.  Raycasts are performed
against the track-outline polyline (same geometry the path-finder uses),
NOT the collision mesh.

Inputs (28):
    0  forward_vel        body-frame forward speed (px/frame), normalized
    1  lateral_vel        body-frame lateral speed (px/frame), normalized
    2  angular_vel        yaw rate (deg/frame), normalized
    3  abs_vel            world-frame speed magnitude (px/frame), normalized
    4  grip_FL            front-left wheel grip  [0..1]
    5  grip_FR            front-right wheel grip [0..1]
    6  grip_RL            rear-left  wheel grip  [0..1]
    7  grip_RR            rear-right wheel grip  [0..1]
    8  dist_from_path     signed distance from perfect racing line, normalized
    9  angle_from_path    angle difference to path tangent, normalized
   10..16  7 raycasts     distances to track edge (polyline), normalized
   17 in_bounds           1.0 if on track, 0.0 if off track
    18 tangent_300_ahead   angle diff to path tangent 300 px ahead, normalized
    19 tangent_600_ahead   angle diff to path tangent 600 px ahead, normalized
    20 tangent_900_ahead   angle diff to path tangent 900 px ahead, normalized
    21 car_mass            normalized mass of the car
    22 car_hp              normalized horsepower
    23 car_front_grip      front wheel grip from specs
    24 car_rear_grip       rear wheel grip from specs
    25 car_cornering       cornering stiffness from specs
    26 car_stiffness       wheel stiffness factor from specs
    27 car_drivetrain      -1.0 FWD, 0.0 AWD/AWDS, 1.0 RWD

Outputs (3):
    throttle  [-1..1]  (tanh)
    steering  [-1..1]  (tanh)
    brake     [ 0..1]  (sigmoid)
"""

# === imports ================================================================
import sys, os, math, pickle, json, time
import numpy as np
from concurrent.futures import ThreadPoolExecutor

# Make project importable when running from tools/
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import pygame

from drift.tools.paths import normalize_asset_path
import drift.config.const as const
import drift.core.car as car_module
from drift.core.helpers import clamp


# === constants ==============================================================
POPULATION_SIZE   = 40
HIDDEN_SIZES      = [24, 18, 18]
INPUT_SIZE        = 28
OUTPUT_SIZE       = 3
MAX_EPISODE_STEPS = 1500
SIM_DT            = 1.0 / 60.0        # fixed physics timestep
INPUT_TAU         = 0.1                # low-pass filter time constant (seconds)
INPUT_ALPHA       = SIM_DT / (INPUT_TAU + SIM_DT)  # EMA smoothing factor
RAYCAST_ANGLES_DEG = [-90, -60, -30, 0, 30, 60, 90]  # 7 rays
MAX_RAY_DIST      = 500.0
SPEED_NORM        = 1000.0             # normalisation constant for velocities
SPEED_NORM_FRAME  = SPEED_NORM * SIM_DT
ANGVEL_NORM       = 20.0
ANGVEL_NORM_FRAME = ANGVEL_NORM * SIM_DT
SAVE_EVERY_GEN    = 5
_SQRT2            = math.sqrt(2)       # undo isometric Y compensation from car.step()

# === GLOBAL REWARD SCALING ===
REWARD_SCALE = 1.0 / 1000.0

CHECKPOINT_REWARD = 20.0 * REWARD_SCALE
## Drift reward/penalty removed
WRONG_WAY_ANGLE_THRESHOLD = math.pi * 0.75
WRONG_WAY_KILL_PENALTY = 4000.0 * REWARD_SCALE
LOOKAHEAD_DIST_1 = 300.0
LOOKAHEAD_DIST_2 = 600.0
LOOKAHEAD_DIST_3 = 900.0
DEAD_FRAME_PENALTY = -200.0 * REWARD_SCALE

# Available car types (folder names under assets/cars/)
CAR_TYPES = ["911", "AE86", "barracuda", "mustang", "r34"]

def _load_all_car_specs():
    """Load specs.json for every car type. Returns dict {car_type: raw_specs}."""
    specs = {}
    for ct in CAR_TYPES:
        p = normalize_asset_path("cars", ct, "specs.json")
        with open(p, "r", encoding="utf-8") as f:
            specs[ct] = json.load(f)
    return specs

def _car_spec_inputs(raw_specs):
    """Return 7 normalized floats describing the car's physics profile."""
    s = raw_specs
    mass = s.get("specs", {}).get("mass", 1150)
    hp   = s.get("specs", {}).get("horsepower", 200)
    fg   = s.get("physics", {}).get("wheels", {}).get("front_grip", 1.0)
    rg   = s.get("physics", {}).get("wheels", {}).get("rear_grip", 1.0)
    cs   = s.get("physics", {}).get("cornering_stiffness", 0.8)
    sf   = s.get("physics", {}).get("wheels", {}).get("stiffness_factor", 0.8)
    dt   = s.get("specs", {}).get("drivetrain", s.get("drivetrain", "RWD"))
    dt_val = {"FWD": -1.0, "AWD": 0.0, "AWDS": 0.0, "RWD": 1.0}.get(dt, 1.0)
    return (
        clamp((mass - 800) / 1000.0, 0.0, 1.0),   # 800..1800 -> 0..1
        clamp((hp - 100) / 350.0, 0.0, 1.0),       # 100..450  -> 0..1
        clamp(fg, 0.0, 2.0),
        clamp(rg, 0.0, 2.0),
        clamp(cs / 2.0, 0.0, 1.0),                  # 0..2  -> 0..1
        clamp(sf, 0.0, 1.0),
        dt_val,                                      # -1 FWD, 0 AWD, 1 RWD
    )

# === neural network =========================================================

class NeuralNetwork:
    """Small feed-forward net: tanh hidden layers, mixed output activations."""

    def __init__(self, in_size=INPUT_SIZE, hidden=None, out_size=OUTPUT_SIZE):
        if hidden is None:
            hidden = list(HIDDEN_SIZES)
        self.in_size = in_size
        self.hidden = hidden
        self.out_size = out_size
        self.layers = []
        sizes = [in_size] + hidden + [out_size]
        for i in range(len(sizes) - 1):
            w = np.random.randn(sizes[i], sizes[i + 1]) * np.sqrt(2.0 / sizes[i])
            b = np.zeros((1, sizes[i + 1]))
            self.layers.append({"w": w, "b": b})

    def forward(self, x):
        x = np.asarray(x, dtype=np.float64).reshape(1, -1)
        for i, layer in enumerate(self.layers):
            x = x @ layer["w"] + layer["b"]
            if i < len(self.layers) - 1:
                x = np.tanh(x)
            else:
                x = np.concatenate([
                    np.tanh(x[:, :2]),
                    1.0 / (1.0 + np.exp(-np.clip(x[:, 2:], -10, 10)))
                ], axis=1)
        return x.flatten()

    def get_weights(self):
        parts = []
        for l in self.layers:
            parts.append(l["w"].ravel())
            parts.append(l["b"].ravel())
        return np.concatenate(parts)

    def set_weights(self, flat):
        idx = 0
        for l in self.layers:
            ws = l["w"].size
            l["w"] = flat[idx:idx + ws].reshape(l["w"].shape)
            idx += ws
            bs = l["b"].size
            l["b"] = flat[idx:idx + bs].reshape(l["b"].shape)
            idx += bs

    def copy(self):
        nn = NeuralNetwork(self.in_size, list(self.hidden), self.out_size)
        nn.set_weights(self.get_weights().copy())
        return nn

    def mutate(self, rate=0.01, strength=0.15):
        for l in self.layers:
            for arr in (l["w"], l["b"]):
                mask = np.random.random(arr.shape) < rate
                noise = np.where(
                    np.random.random(arr.shape) < 0.8,
                    np.random.normal(0, strength * 0.5, arr.shape),
                    np.random.normal(0, strength * 2.0, arr.shape),
                )
                arr += mask * noise


# === genetic algorithm ======================================================

class GeneticAlgorithm:
    def __init__(self, pop_size=POPULATION_SIZE):
        self.pop_size = pop_size
        self.generation = 0
        self.population = [NeuralNetwork() for _ in range(pop_size)]
        self.fitness = np.zeros(pop_size)
        self.best_fitness = -float("inf")
        self.best_net = None
        self.mutation_scale = 1.0  # multiplied into all mutation rates/strengths

    def _estimate_mutation_scale_from_generation(self, generation):
        # Fallback for old checkpoints that do not persist mutation_scale.
        # Keeps late-generation resumes from jumping back to 1.0 exploration.
        g = max(0, int(generation))
        estimated = 0.95 ** (g / 10.0)
        return float(clamp(estimated, 0.05, 1.0))

    def reseed_population_from_best(self):
        if self.best_net is None:
            return False

        # Checkpoints only persist the champion, so rebuild a fresh population
        # around that network instead of silently starting from random weights.
        new_pop = [self.best_net.copy()]
        while len(new_pop) < self.pop_size:
            idx = len(new_pop)
            if idx >= self.pop_size - 4:
                new_pop.append(NeuralNetwork())
                continue

            child = self.best_net.copy()
            if idx < 6:
                child.mutate(rate=0.03, strength=0.30)
            else:
                child.mutate(rate=0.01, strength=0.12)
            new_pop.append(child)

        self.population = new_pop
        self.fitness = np.zeros(self.pop_size)
        return True

    # -- selection / crossover / mutation ------------------------------------
    def _tournament(self, k=3):
        idxs = np.random.choice(self.pop_size, k, replace=False)
        winner = idxs[np.argmax(self.fitness[idxs])]
        return self.population[winner]

    def _crossover(self, p1, p2):
        child = NeuralNetwork()
        w1, w2 = p1.get_weights(), p2.get_weights()
        mask = np.random.random(len(w1)) < 0.5
        child.set_weights(np.where(mask, w1, w2))
        return child

    def evolve(self):
        self.generation += 1
        order = np.argsort(self.fitness)[::-1]

        # update best
        if self.fitness[order[0]] > self.best_fitness:
            self.best_fitness = self.fitness[order[0]]
            self.best_net = self.population[order[0]].copy()

        # Always keep one exact, unmutated champion as a safety anchor.
        locked_champion = (self.best_net.copy()
                           if self.best_net is not None
                           else self.population[order[0]].copy())

        elite_n = max(1, self.pop_size // 10)
        new_pop = [locked_champion]
        for i in range(1, elite_n):
            new_pop.append(self.population[order[i]].copy())

        ms = self.mutation_scale
        explorers = 0
        while len(new_pop) < self.pop_size:
            child = self._crossover(self._tournament(), self._tournament())
            if explorers < 5:
                child.mutate(rate=0.03 * ms, strength=0.4 * ms)
                explorers += 1
            elif len(new_pop) < elite_n + int(self.pop_size * 0.3):
                child.mutate(rate=0.005 * ms, strength=0.08 * ms)
            else:
                child.mutate(rate=0.01 * ms, strength=0.15 * ms)
            new_pop.append(child)

        self.population = new_pop
        self.fitness = np.zeros(self.pop_size)

    # -- persistence ---------------------------------------------------------
    def save(self, path):
        if self.best_net is None:
            return
        with open(path, "wb") as f:
            pickle.dump({
                "weights": self.best_net.get_weights(),
                "arch": {"in": INPUT_SIZE, "hidden": list(HIDDEN_SIZES), "out": OUTPUT_SIZE},
                "generation": self.generation,
                "fitness": float(self.best_fitness),
                "mutation_scale": float(self.mutation_scale),
            }, f)
        print(f"  [save] gen {self.generation}  fitness {self.best_fitness:.1f}  -> {path}")

    def load(self, path):
        if not os.path.exists(path):
            print(f"  [load] not found: {path}")
            return False
        try:
            with open(path, "rb") as f:
                d = pickle.load(f)
            # Support both new ("arch") and old ("architecture") key names
            arch = d.get("arch") or d.get("architecture", {})
            in_s = arch.get("in") or arch.get("input_size", INPUT_SIZE)
            hid = arch.get("hidden") or arch.get("hidden_sizes", list(HIDDEN_SIZES))
            out_s = arch.get("out") or arch.get("output_size", OUTPUT_SIZE)
            # Only restore if architecture matches current config
            if in_s != INPUT_SIZE or out_s != OUTPUT_SIZE:
                print(f"  [load] architecture mismatch ({in_s}->{out_s} vs "
                      f"{INPUT_SIZE}->{OUTPUT_SIZE}).  Starting fresh.")
                return False
            net = NeuralNetwork(in_s, list(hid), out_s)
            net.set_weights(d["weights"])
            self.best_net = net
            self.best_fitness = d.get("fitness", 0.0)
            self.generation = d.get("generation", 0)
            if "mutation_scale" in d:
                self.mutation_scale = float(clamp(d["mutation_scale"], 0.2, 2.0))
            else:
                self.mutation_scale = self._estimate_mutation_scale_from_generation(self.generation)
            self.reseed_population_from_best()
            print(f"  [load] gen {self.generation}  fitness {self.best_fitness:.1f}  "
                  f"ms {self.mutation_scale:.3f}  <- {path}")
            return True
        except Exception as e:
            print(f"  [load] error: {e}")
            return False


# === track polyline helpers =================================================

def _downsample_polyline(pts, min_dist=12.0):
    """Remove points closer than *min_dist* to reduce segment count."""
    if len(pts) < 4:
        return list(pts)
    out = [pts[0]]
    md2 = min_dist * min_dist
    for p in pts[1:]:
        dx, dy = p[0] - out[-1][0], p[1] - out[-1][1]
        if dx * dx + dy * dy >= md2:
            out.append(p)
    return out


def _load_path_polyline(map_num=1):
    """Discover the track center-line polyline (same algorithm as path_finder)."""
    from drift.ai.path_finder import discover_track
    img_path = str(normalize_asset_path("track", f"map{map_num}", "main.png"))

    # Load map_meta for start position
    meta_path = normalize_asset_path("track", f"map{map_num}", "map_meta.json")
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    starts = meta.get("start", [])
    if starts:
        sx, sy = starts[0]["x"], starts[0]["y"]
        sa = math.degrees(starts[0].get("a", math.pi / 2))
    else:
        sx, sy, sa = 220, 1700, 90

    print(f"  Discovering track polyline from map{map_num} ...")
    poly = discover_track(img_path, start_pos=(sx, sy), start_angle=sa,
                          sample_rate=4, max_iterations=20000)
    print(f"  Raw polyline: {len(poly)} points")
    poly = _downsample_polyline(poly, min_dist=12.0)
    print(f"  Downsampled:  {len(poly)} points")
    return poly, meta


def _build_edge_segments(polyline, half_width=70):
    """Expand center-line into left/right edge polylines.

    Returns two lists of (x,y) tuples: left_edge, right_edge.
    These form the track boundary the raycasts will hit.
    """
    if len(polyline) < 3:
        return [], []

    left, right = [], []
    n = len(polyline)
    for i in range(n):
        ax, ay = polyline[i]
        bx, by = polyline[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        nx, ny = -dy / length, dx / length  # left normal
        left.append((ax + nx * half_width, ay + ny * half_width))
        right.append((ax - nx * half_width, ay - ny * half_width))
    return left, right


# === fast segment-ray intersection ==========================================

def _segments_from_polyline(pts):
    """Return list of ((x1,y1),(x2,y2)) from a closed polyline."""
    segs = []
    n = len(pts)
    for i in range(n):
        segs.append((pts[i], pts[(i + 1) % n]))
    return segs


class SegmentGrid:
    """Spatial grid that accelerates ray-vs-segment queries."""

    def __init__(self, segments, cell=120.0):
        self.cell = cell
        self.inv = 1.0 / cell
        self.segments = segments
        self.grid = {}  # (cx,cy) -> list of segment indices
        for idx, ((ax, ay), (bx, by)) in enumerate(segments):
            min_x = min(ax, bx)
            max_x = max(ax, bx)
            min_y = min(ay, by)
            max_y = max(ay, by)
            cx0 = int(math.floor(min_x * self.inv))
            cx1 = int(math.floor(max_x * self.inv))
            cy0 = int(math.floor(min_y * self.inv))
            cy1 = int(math.floor(max_y * self.inv))
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    key = (cx, cy)
                    if key not in self.grid:
                        self.grid[key] = []
                    self.grid[key].append(idx)

    def query_ray(self, ox, oy, dx, dy, max_dist):
        """Step the ray through the grid, testing only nearby segments.
        Returns (best_t, hit_bool)."""
        inv = self.inv
        segs = self.segments
        best_t = max_dist
        hit = False
        tested = set()

        # DDA-style grid traversal
        cx = int(math.floor(ox * inv))
        cy = int(math.floor(oy * inv))
        step_x = 1 if dx >= 0 else -1
        step_y = 1 if dy >= 0 else -1

        # distance to next cell boundary in t-units
        cell = self.cell
        if abs(dx) > 1e-12:
            if dx > 0:
                t_max_x = ((cx + 1) * cell - ox) / dx
            else:
                t_max_x = (cx * cell - ox) / dx
            t_delta_x = abs(cell / dx)
        else:
            t_max_x = float("inf")
            t_delta_x = float("inf")

        if abs(dy) > 1e-12:
            if dy > 0:
                t_max_y = ((cy + 1) * cell - oy) / dy
            else:
                t_max_y = (cy * cell - oy) / dy
            t_delta_y = abs(cell / dy)
        else:
            t_max_y = float("inf")
            t_delta_y = float("inf")

        t_cur = 0.0
        while t_cur < best_t:
            bucket = self.grid.get((cx, cy))
            if bucket:
                for si in bucket:
                    if si in tested:
                        continue
                    tested.add(si)
                    (ax, ay), (bx, by) = segs[si]
                    ex, ey = bx - ax, by - ay
                    denom = dx * ey - dy * ex
                    if abs(denom) < 1e-12:
                        continue
                    inv_d = 1.0 / denom
                    t = ((ax - ox) * ey - (ay - oy) * ex) * inv_d
                    u = ((ax - ox) * dy - (ay - oy) * dx) * inv_d
                    if 0 <= t < best_t and 0 <= u <= 1:
                        best_t = t
                        hit = True

            # advance to next grid cell
            if t_max_x < t_max_y:
                t_cur = t_max_x
                t_max_x += t_delta_x
                cx += step_x
            else:
                t_cur = t_max_y
                t_max_y += t_delta_y
                cy += step_y

        return best_t, hit


def raycast_grid(grid, ox, oy, angle, max_dist):
    """High-level raycast returning (hx, hy, dist, hit)."""
    dx = math.cos(angle)
    dy = math.sin(angle)
    best_t, hit = grid.query_ray(ox, oy, dx, dy, max_dist)
    return ox + dx * best_t, oy + dy * best_t, best_t, hit


def raycast_segments(segments, ox, oy, angle, max_dist):
    """Brute-force fallback (used only for drawing)."""
    dx = math.cos(angle)
    dy = math.sin(angle)
    best_t = max_dist
    hit = False
    for (ax, ay), (bx, by) in segments:
        ex, ey = bx - ax, by - ay
        denom = dx * ey - dy * ex
        if abs(denom) < 1e-12:
            continue
        inv_d = 1.0 / denom
        t = ((ax - ox) * ey - (ay - oy) * ex) * inv_d
        u = ((ax - ox) * dy - (ay - oy) * dx) * inv_d
        if 0 <= t < best_t and 0 <= u <= 1:
            best_t = t
            hit = True
    return ox + dx * best_t, oy + dy * best_t, best_t, hit


# === point-on-polyline utilities ============================================

def _nearest_on_polyline(px, py, poly, hint_seg=0, search_window=60):
    """Return (closest_x, closest_y, seg_idx, t, sqr_dist).

    *hint_seg* + *search_window* restrict the search to nearby segments for
    O(window) instead of O(n) per call.
    """
    best_d2 = float("inf")
    best_cx, best_cy = px, py
    best_idx = 0
    best_t = 0.0
    n = len(poly)
    start = (hint_seg - search_window) % n
    for off in range(search_window * 2 + 1):
        i = (start + off) % n
        j = (i + 1) % n
        ax, ay = poly[i]
        bx, by = poly[j]
        vx, vy = bx - ax, by - ay
        denom = vx * vx + vy * vy
        if denom < 1e-8:
            continue
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
        cx, cy = ax + vx * t, ay + vy * t
        d2 = (px - cx) ** 2 + (py - cy) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_cx, best_cy = cx, cy
            best_idx = i
            best_t = t
    return best_cx, best_cy, best_idx, best_t, best_d2


def _path_tangent_angle(poly, seg_idx):
    """Angle of the tangent at segment seg_idx."""
    n = len(poly)
    ax, ay = poly[seg_idx]
    bx, by = poly[(seg_idx + 1) % n]
    return math.atan2(by - ay, bx - ax)


def _advance_along_polyline(poly, seg_idx, t, distance):
    """Advance forward along a closed polyline by *distance* world units.

    Returns (x, y, seg_idx, t) at the advanced point.
    """
    n = len(poly)
    if n < 2:
        ax, ay = poly[0]
        return ax, ay, 0, 0.0

    i = seg_idx % n
    local_t = float(clamp(t, 0.0, 1.0))
    remaining = max(0.0, float(distance))

    while True:
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg_len = math.hypot(dx, dy)
        if seg_len < 1e-8:
            i = (i + 1) % n
            local_t = 0.0
            continue

        dist_left = seg_len * (1.0 - local_t)
        if remaining <= dist_left:
            new_t = local_t + (remaining / seg_len)
            return ax + dx * new_t, ay + dy * new_t, i, new_t

        remaining -= dist_left
        i = (i + 1) % n
        local_t = 0.0


def _relative_angle_to_path_tangent(car_angle, poly, seg_idx, t, lookahead_distance):
    """Return normalized angle diff to the path tangent lookahead_distance ahead."""
    _, _, ahead_seg, _ = _advance_along_polyline(poly, seg_idx, t, lookahead_distance)
    ahead_tangent = _path_tangent_angle(poly, ahead_seg)
    ahead_angle_diff = ((car_angle - ahead_tangent + math.pi) % (2 * math.pi)) - math.pi
    return clamp(ahead_angle_diff / math.pi, -1.0, 1.0), ahead_tangent, ahead_seg


def _signed_distance(px, py, poly, seg_idx, t):
    """Signed distance: positive = left of path, negative = right."""
    n = len(poly)
    ax, ay = poly[seg_idx]
    bx, by = poly[(seg_idx + 1) % n]
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-8:
        return 0.0
    nx, ny = -dy / length, dx / length  # left normal
    cx, cy = ax + (bx - ax) * t, ay + (by - ay) * t
    return (px - cx) * nx + (py - cy) * ny


# === point-in-track test ====================================================

def _point_in_closed_poly(px, py, poly):
    """Ray-casting point-in-polygon (for the track boundary)."""
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_any_zone(px, py, zones):
    """Check if point (px, py) is inside any of the zones (list of polygons)."""
    if not zones:
        return False
    for zone in zones:
        if _point_in_closed_poly(px, py, zone):
            return True
    return False


# === training environment ===================================================

class TrainingEnv:
    """Headless-capable training env using real game physics."""

    def __init__(self, polyline, meta, num_cars=POPULATION_SIZE):
        self.polyline = polyline       # center-line
        self.meta = meta
        self.num_cars = num_cars

        # Build evenly-spaced virtual checkpoints directly from the discovered path.
        n_poly = max(1, len(polyline))
        checkpoint_count = max(8, min(80, n_poly // 5))
        step = max(1, n_poly // checkpoint_count)
        self.poly_checkpoint_segments = list(range(0, n_poly, step))
        if not self.poly_checkpoint_segments:
            self.poly_checkpoint_segments = [0]

        # Pre-load all car specs so reset() can pick randomly
        self.all_specs = _load_all_car_specs()
        self.car_spec_cache = {}   # car_type -> 6-float tuple
        for ct, raw in self.all_specs.items():
            self.car_spec_cache[ct] = _car_spec_inputs(raw)
        self.car_types = []        # per-car type string, set in reset()

        # Build track edges for raycasting
        left_edge, right_edge = _build_edge_segments(polyline, half_width=70)
        edge_segs = _segments_from_polyline(left_edge) + _segments_from_polyline(right_edge)
        self.edge_segments = edge_segs
        self.edge_grid = SegmentGrid(edge_segs, cell=120.0)

        # For in_bounds testing build a closed track polygon (left + reversed right)
        # Downsample it for faster point-in-polygon tests
        combined = left_edge + list(reversed(right_edge))
        self.track_polygon = _downsample_polyline(combined, min_dist=20.0)

        self.ray_angles_rad = [math.radians(a) for a in RAYCAST_ANGLES_DEG]

        # Spawn info
        starts = meta.get("start", [])
        if starts:
            self.spawn_x = starts[0]["x"]-40
            self.spawn_y = starts[0]["y"]
            self.spawn_a = starts[0].get("a", 0.0)
        else:
            self.spawn_x, self.spawn_y, self.spawn_a = 285, 1805, 1.57

        # Checkpoints for progress tracking
        self.checkpoints = []
        for cp in meta.get("checkpoints", []):
            cx = cp["x"] + cp["width"] / 2
            cy = cp["y"] + cp["height"] / 2
            self.checkpoints.append((cx, cy))

        # Drift zones removed

        self.cars = []
        self.in_bounds = []
        self.step_count = 0
        self.car_progress = []      # cumulative path-distance traveled
        self.car_prev_seg = []
        self.car_next_checkpoint = []
        self.car_checkpoint_hits = []
        self.car_checkpoint_flash = []
        self.car_last_checkpoint_gain = []
        # Drift state removed
        self.car_oob_frames = []
        self.car_alive = []
        self.smoothed_actions = []    # low-pass filtered inputs per car
        self.debug_car_idx = -1       # index of car that gets compute_debug=True
        self.epoch_car_type = None

    # -- reset ---------------------------------------------------------------
    def reset(self, keep_car_type=False):
        self.cars = []
        self.in_bounds = [1.0] * self.num_cars
        self.step_count = 0
        self.car_progress = [0.0] * self.num_cars
        self.car_prev_seg = [0] * self.num_cars
        self.car_next_checkpoint = [0] * self.num_cars
        self.car_checkpoint_hits = [0] * self.num_cars
        self.car_checkpoint_flash = [0] * self.num_cars
        self.car_last_checkpoint_gain = [0] * self.num_cars
        # Drift state removed
        self.car_oob_frames = [0] * self.num_cars
        self.car_alive = [True] * self.num_cars
        self.smoothed_actions = [np.array([0.0, 0.0, 0.0]) for _ in range(self.num_cars)]

        # Find the closest polyline segment to the spawn (full search, once)
        _, _, spawn_seg, _, _ = _nearest_on_polyline(
            self.spawn_x, self.spawn_y, self.polyline,
            hint_seg=0, search_window=len(self.polyline) // 2)

        # Choose a single car type for the entire epoch.
        # If the previous episode ended by full wipeout, keep the same model.
        if keep_car_type and self.epoch_car_type in CAR_TYPES:
            epoch_car_type = self.epoch_car_type
        else:
            epoch_car_type = CAR_TYPES[np.random.randint(len(CAR_TYPES))]
        self.epoch_car_type = epoch_car_type

        # Start each car from the first checkpoint ahead of the spawn segment.
        spawn_mod = spawn_seg % len(self.polyline)
        next_cp_idx = 0
        for idx, cp_seg in enumerate(self.poly_checkpoint_segments):
            if cp_seg > spawn_mod:
                next_cp_idx = idx
                break

        self.car_types = [epoch_car_type] * self.num_cars
        for i in range(self.num_cars):
            c = car_module.Car(self.spawn_x, self.spawn_y,
                               f"T_{i}", is_ai=True, car_type=epoch_car_type)
            c.angle = self.spawn_a
            # small initial forward push so the car is not fully stationary
            c.vx = math.cos(c.angle) * 60
            c.vy = math.sin(c.angle) * 60
            self.cars.append(c)
            self.car_prev_seg[i] = spawn_seg
            self.car_next_checkpoint[i] = next_cp_idx

        # Build initial observations (no-op action)
        obs = []
        for i, c in enumerate(self.cars):
            fwd_x, fwd_y = math.cos(c.angle), math.sin(c.angle)
            rgt_x, rgt_y = -fwd_y, fwd_x
            spec_in = self.car_spec_cache[self.car_types[i]]
            grip = c.has_grip
            obs.append(np.zeros(INPUT_SIZE, dtype=np.float32))
        return obs

    # -- step ----------------------------------------------------------------
    _thread_pool = None

    def _get_pool(self):
        if TrainingEnv._thread_pool is None:
            TrainingEnv._thread_pool = ThreadPoolExecutor(
                max_workers=min(8, os.cpu_count() or 4))
        return TrainingEnv._thread_pool

    def _process_car(self, i, action):
        """Process physics, reward, and observation for one car.

        Returns (reward, obs, alive, in_bounds_val, progress_delta, new_seg).
        This is called from threads -- only reads shared data (polyline,
        edge_grid, ray_angles_rad) and mutates only the car object for index i.
        """
        c = self.cars[i]
        if not self.car_alive[i]:
            return DEAD_FRAME_PENALTY, np.zeros(INPUT_SIZE, dtype=np.float32), False, self.in_bounds[i], 0, self.car_prev_seg[i]

        # Low-pass filter the raw NN output
        raw = np.array([float(np.clip(action[0], -1, 1)),
                        float(np.clip(action[1], -1, 1)),
                        float(np.clip(action[2], 0, 1))])
        prev = self.smoothed_actions[i]
        smoothed = prev + INPUT_ALPHA * (raw - prev)
        self.smoothed_actions[i] = smoothed

        inp = {
            "th": float(smoothed[0]),
            "st": float(smoothed[1]),
            "br": float(smoothed[2]),
        }
        prev_y = c.y

        c.step(inp, SIM_DT, {}, (50000, 50000),
               compute_debug=(i == self.debug_car_idx))

        # Undo the isometric sqrt(2) Y stretch from car.step()
        c.y = prev_y + (c.y - prev_y) / _SQRT2

        # Nearest point on polyline (done ONCE, reused for everything)
        hint = self.car_prev_seg[i]
        cx, cy, seg, t, d2 = _nearest_on_polyline(
            c.x, c.y, self.polyline, hint_seg=hint)

        ib = math.sqrt(d2) < 70.0
        ib_val = 1.0 if ib else 0.0
        if ib:
            self.car_oob_frames[i] = 0
        else:
            self.car_oob_frames[i] += 1

        # Progress along polyline
        seg_advance = seg - hint
        n_segs = len(self.polyline)
        if seg_advance < -n_segs // 2:
            seg_advance += n_segs
        elif seg_advance > n_segs // 2:
            seg_advance -= n_segs
        new_progress = self.car_progress[i] + seg_advance

        # Reward checkpoint crossings along the discovered center-line.
        if ib and seg_advance > 0 and self.poly_checkpoint_segments:
            prev_seg_mod = hint % n_segs
            curr_seg_mod = seg % n_segs
            next_cp_idx = self.car_next_checkpoint[i]
            checkpoint_reward = 0.0
            crossed_count = 0

            for _ in range(len(self.poly_checkpoint_segments)):
                cp_seg = self.poly_checkpoint_segments[next_cp_idx]
                if prev_seg_mod < curr_seg_mod:
                    crossed = prev_seg_mod < cp_seg <= curr_seg_mod
                else:
                    crossed = cp_seg > prev_seg_mod or cp_seg <= curr_seg_mod

                if not crossed:
                    break

                checkpoint_reward += CHECKPOINT_REWARD
                next_cp_idx = (next_cp_idx + 1) % len(self.poly_checkpoint_segments)
                crossed_count += 1

            self.car_next_checkpoint[i] = next_cp_idx
            if crossed_count > 0:
                self.car_checkpoint_hits[i] += crossed_count
                self.car_checkpoint_flash[i] = 24
                self.car_last_checkpoint_gain[i] = crossed_count
        else:
            checkpoint_reward = 0.0

        # 7 raycasts (done ONCE, used for observation)
        rays = []
        for ra in self.ray_angles_rad:
            _, _, rd, hit = raycast_grid(
                self.edge_grid, c.x, c.y, c.angle + ra, MAX_RAY_DIST)
            norm_rd = rd / MAX_RAY_DIST if hit else 1.0
            rays.append(norm_rd)

        dist_from_path = _signed_distance(c.x, c.y, self.polyline, seg, t)

        tang = _path_tangent_angle(self.polyline, seg)
        angle_diff = ((c.angle - tang + math.pi) % (2 * math.pi)) - math.pi
        abs_angle_diff = abs(angle_diff)

        # --- reward ---
        fwd_x, fwd_y = math.cos(c.angle), math.sin(c.angle)
        rgt_x, rgt_y = -fwd_y, fwd_x
        fwd = c.vx * fwd_x + c.vy * fwd_y
        lat = c.vx * rgt_x + c.vy * rgt_y
        speed = math.hypot(c.vx, c.vy)

        reward = 0.0
        wrong_way_kill = False
        #reward += seg_advance * 5.0 * REWARD_SCALE
        reward += (fwd*3.0 if fwd > 0 else fwd * 7.0) * REWARD_SCALE
        reward += checkpoint_reward
        reward -= abs(dist_from_path) * REWARD_SCALE
        if abs_angle_diff > WRONG_WAY_ANGLE_THRESHOLD:
            reward -= WRONG_WAY_KILL_PENALTY
            wrong_way_kill = True


        # Drift reward/penalty logic removed

        alive = not wrong_way_kill

        if fwd < 10:
            reward -= 50 * REWARD_SCALE
        if speed < 5:
            reward -= 50 * REWARD_SCALE
        if speed < 5 and self.step_count > 120:
            alive = False
        if new_progress < -5:
            alive = False
        if self.car_oob_frames[i] > 120:
            alive = False

        if not alive and not wrong_way_kill:
            reward -= 2000.0 * REWARD_SCALE

        if not ib and not wrong_way_kill:
            reward = 0.0

        # --- observation ---
        dist_norm = clamp(dist_from_path / 150.0, -1.0, 1.0)
        angle_norm = clamp(angle_diff / math.pi, -1.0, 1.0)
        tang_300_norm, _, _ = _relative_angle_to_path_tangent(
            c.angle, self.polyline, seg, t, LOOKAHEAD_DIST_1)
        tang_600_norm, _, _ = _relative_angle_to_path_tangent(
            c.angle, self.polyline, seg, t, LOOKAHEAD_DIST_2)
        tang_900_norm, _, _ = _relative_angle_to_path_tangent(
            c.angle, self.polyline, seg, t, LOOKAHEAD_DIST_3)

        spec_in = self.car_spec_cache[self.car_types[i]]
        grip = c.has_grip

        obs = np.array([
            (c.vx * fwd_x + c.vy * fwd_y) * SIM_DT / SPEED_NORM_FRAME,
            (c.vx * rgt_x + c.vy * rgt_y) * SIM_DT / SPEED_NORM_FRAME,
            clamp(c.v_angle * SIM_DT / ANGVEL_NORM_FRAME, -1.0, 1.0),
            math.hypot(c.vx, c.vy) * SIM_DT / SPEED_NORM_FRAME,
            grip[0], grip[1], grip[2], grip[3],
            dist_norm, angle_norm,
            *rays,
            ib_val,
            tang_300_norm,
            tang_600_norm,
            tang_900_norm,
            *spec_in,
        ], dtype=np.float32)

        return reward, obs, alive, ib_val, seg_advance, seg

    def step(self, actions):
        """Run one timestep for all cars using a thread pool."""
        self.step_count += 1
        pool = self._get_pool()

        # Submit all alive cars to the thread pool
        futures = {}
        for i in range(self.num_cars):
            futures[i] = pool.submit(self._process_car, i, actions[i])

        # Collect results
        rewards = np.zeros(self.num_cars)
        observations = []
        for i in range(self.num_cars):
            reward, obs, alive, ib_val, seg_adv, new_seg = futures[i].result()
            rewards[i] = reward
            observations.append(obs)
            self.in_bounds[i] = ib_val
            self.car_progress[i] += seg_adv
            self.car_prev_seg[i] = new_seg
            if not alive:
                self.car_alive[i] = False

            if self.car_checkpoint_flash[i] > 0:
                self.car_checkpoint_flash[i] -= 1
                if self.car_checkpoint_flash[i] == 0:
                    self.car_last_checkpoint_gain[i] = 0

        done = self.step_count >= MAX_EPISODE_STEPS or not any(self.car_alive)
        return observations, rewards, done


# === simple renderer (optional) =============================================

def draw_cars_simple(surface, cars, alive, scale=0.5, only_indices=None):
    halfL = car_module.CAR_LEN * 0.5
    halfW = car_module.CAR_WID * 0.5
    for idx, c in enumerate(cars):
        if not alive[idx]:
            continue
        if only_indices is not None and idx not in only_indices:
            continue
        ca, sa = math.cos(c.angle), math.sin(c.angle)
        pts = []
        for lx, ly in ((halfL, halfW), (halfL, -halfW),
                        (-halfL, -halfW), (-halfL, halfW)):
            rx = lx * ca - ly * sa
            ry = lx * sa + ly * ca
            pts.append((int((c.x + rx) * scale), int((c.y + ry) * scale)))

        color = (100, 220, 100) if alive[idx] else (100, 100, 100)
        pygame.draw.polygon(surface, color, pts)

        # nose tick
        fx = c.x + ca * halfL
        fy = c.y + sa * halfL
        nx = fx + ca * 6
        ny = fy + sa * 6
        pygame.draw.line(surface, (255, 120, 120),
                         (int(fx * scale), int(fy * scale)),
                         (int(nx * scale), int(ny * scale)), 2)


def draw_track_outline(surface, left_edge, right_edge, scale=0.5):
    if len(left_edge) > 2:
        pts = [(int(x * scale), int(y * scale)) for x, y in left_edge]
        pygame.draw.polygon(surface, (60, 60, 60), pts, 1)
    if len(right_edge) > 2:
        pts = [(int(x * scale), int(y * scale)) for x, y in right_edge]
        pygame.draw.polygon(surface, (60, 60, 60), pts, 1)


def draw_poly_checkpoints(surface, polyline, checkpoint_segments, scale=0.5):
    if not polyline or not checkpoint_segments:
        return

    for cp_idx, seg_idx in enumerate(checkpoint_segments):
        x, y = polyline[seg_idx]
        sx = int(x * scale)
        sy = int(y * scale)

        # Outer ring + center dot so checkpoints stay visible over track lines.
        pygame.draw.circle(surface, (255, 165, 0), (sx, sy), 5, 2)
        pygame.draw.circle(surface, (255, 220, 120), (sx, sy), 2)

        # Label every 5th checkpoint to reduce clutter on dense tracks.
        if cp_idx % 5 == 0:
            pygame.draw.circle(surface, (40, 40, 40), (sx + 9, sy - 9), 6)
            pygame.draw.circle(surface, (240, 240, 240), (sx + 9, sy - 9), 6, 1)


# === physics debug window ===================================================

DEBUG_WIN_SIZE = 500         # square debug viewport in pixels
DEBUG_WORLD_RADIUS = 550.0   # how many world-units around the car are visible

_debug_font = None



def draw_debug_view(surface, car, edge_segments, ray_angles_rad, edge_grid,
                   polyline, seg_hint, left_edge, right_edge,
                   checkpoint_segments=None, next_checkpoint_idx=0,
                   checkpoint_hits=0, checkpoint_flash=0,
                   last_checkpoint_gain=0):
    """Render a zoomed, car-centered physics debug view onto *surface*.

    Reproduces the same debug overlays the game uses (wheel grip circles,
    wheel heading arrows, lateral-force arrows) plus raycasts, velocity
    vectors and a text HUD.
    """
    global _debug_font
    if _debug_font is None:
        _debug_font = pygame.font.Font(None, 18)
    font = _debug_font

    W = surface.get_width()
    H = surface.get_height()
    surface.fill((20, 22, 28))

    # World -> screen transform: car at center, zoom to fit DEBUG_WORLD_RADIUS
    zoom = min(W, H) / (2.0 * DEBUG_WORLD_RADIUS)
    cx_w, cy_w = car.x, car.y   # world center
    half_w, half_h = W / 2.0, H / 2.0

    def w2s(wx, wy):
        """World coord -> screen pixel."""
        return (int((wx - cx_w) * zoom + half_w),
                int((wy - cy_w) * zoom + half_h))

    # -- track edges (only segments within view) --
    view_r2 = (DEBUG_WORLD_RADIUS + 100) ** 2
    for edge in (left_edge, right_edge):
        n = len(edge)
        for i in range(n):
            ax, ay = edge[i]
            bx, by = edge[(i + 1) % n]
            if ((ax - cx_w)**2 + (ay - cy_w)**2 < view_r2 or
                    (bx - cx_w)**2 + (by - cy_w)**2 < view_r2):
                pygame.draw.line(surface, (55, 55, 55), w2s(ax, ay), w2s(bx, by), 1)

    # -- centerline (nearby segments) --
    n_poly = len(polyline)
    for off in range(-40, 41):
        i = (seg_hint + off) % n_poly
        j = (i + 1) % n_poly
        ax, ay = polyline[i]
        bx, by = polyline[j]
        pygame.draw.line(surface, (40, 50, 65), w2s(ax, ay), w2s(bx, by), 1)

    # -- virtual checkpoints from polyline --
    checkpoint_segments = checkpoint_segments or []
    if checkpoint_segments:
        next_cp_seg = checkpoint_segments[next_checkpoint_idx % len(checkpoint_segments)]
        for cp_idx, cp_seg in enumerate(checkpoint_segments):
            cpx, cpy = polyline[cp_seg]
            if (cpx - cx_w) ** 2 + (cpy - cy_w) ** 2 > view_r2:
                continue
            pt = w2s(cpx, cpy)
            is_next = (cp_seg == next_cp_seg)
            ring_col = (80, 220, 255) if is_next else (255, 165, 0)
            dot_col = (170, 245, 255) if is_next else (255, 220, 120)
            pygame.draw.circle(surface, ring_col, pt, 6, 2)
            pygame.draw.circle(surface, dot_col, pt, 3)
            if cp_idx % 5 == 0:
                pygame.draw.circle(surface, (18, 20, 24), (pt[0] + 8, pt[1] - 8), 6)
                pygame.draw.circle(surface, (220, 220, 220), (pt[0] + 8, pt[1] - 8), 6, 1)

    # -- raycasts --
    for ra in ray_angles_rad:
        hx, hy, rd, hit = raycast_grid(edge_grid, car.x, car.y,
                                        car.angle + ra, MAX_RAY_DIST)
        col = (0, 160, 0) if hit else (50, 50, 50)
        pygame.draw.line(surface, col, w2s(car.x, car.y), w2s(hx, hy), 1)
        if hit:
            pygame.draw.circle(surface, (0, 220, 0), w2s(hx, hy), 3)

    # -- car body --
    halfL = car_module.CAR_LEN * 0.5
    halfW = car_module.CAR_WID * 0.5
    ca_c, sa_c = math.cos(car.angle), math.sin(car.angle)
    body_pts = []
    for lx, ly in ((halfL, halfW), (halfL, -halfW),
                    (-halfL, -halfW), (-halfL, halfW)):
        rx = lx * ca_c - ly * sa_c
        ry = lx * sa_c + ly * ca_c
        body_pts.append(w2s(car.x + rx, car.y + ry))
    pygame.draw.polygon(surface, (80, 200, 80), body_pts, 2)

    # nose tick
    nose_x = car.x + ca_c * halfL
    nose_y = car.y + sa_c * halfL
    nose_ex = nose_x + ca_c * 8
    nose_ey = nose_y + sa_c * 8
    pygame.draw.line(surface, (255, 100, 100), w2s(nose_x, nose_y),
                     w2s(nose_ex, nose_ey), 2)

    # -- velocity vector (yellow) --
    VEL_SCALE = 0.6
    vex = car.x + car.vx * VEL_SCALE
    vey = car.y + car.vy * VEL_SCALE
    pygame.draw.line(surface, (255, 255, 60), w2s(car.x, car.y),
                     w2s(vex, vey), 2)

    # -- wheel debug (same as game) --
    ANGLE_VEC_LEN = 14.0
    FLAT_SCALE = 0.04
    wheels = []
    grips = getattr(car, "has_grip", (1.0, 1.0, 1.0, 1.0))
    if hasattr(car, "wheel_debug"):
        wheels = car.wheel_debug.get("wheels", [])

    for w in wheels:
        wx, wy = w["world_pos"]
        idx = int(w.get("index", -1))
        grip = grips[idx] if 0 <= idx < len(grips) else 1.0
        sx, sy = w2s(wx, wy)

        # grip dot
        g_col = (int((1.0 - grip) * 255), int(grip * 255), 80)
        pygame.draw.circle(surface, g_col, (sx, sy), 4)

        # wheel heading vector (cyan)
        wheel_angle = w.get("wheel_angle", 0.0)
        total_a = car.angle + wheel_angle
        wa_cos, wa_sin = math.cos(total_a), math.sin(total_a)
        arrow_world_len = ANGLE_VEC_LEN / zoom   # keep arrow constant screen size
        ex_w = wx + wa_cos * arrow_world_len
        ey_w = wy + wa_sin * arrow_world_len
        esx, esy = w2s(ex_w, ey_w)
        pygame.draw.line(surface, (80, 220, 255), (sx, sy), (esx, esy), 1)
        # arrowhead
        ahx, ahy = -wa_sin * 3, wa_cos * 3
        pygame.draw.line(surface, (80, 220, 255), (esx, esy),
                         (int(esx - wa_cos*4 + ahx), int(esy - wa_sin*4 + ahy)), 1)
        pygame.draw.line(surface, (80, 220, 255), (esx, esy),
                         (int(esx - wa_cos*4 - ahx), int(esy - wa_sin*4 - ahy)), 1)

        # lateral force vector (orange)
        f_lat = w.get("F_lat", 0.0)
        lat_ca, lat_sa = math.cos(car.angle + wheel_angle), math.sin(car.angle + wheel_angle)
        lat_wx, lat_wy = -lat_sa, lat_ca
        if abs(f_lat) > 1.0:
            force_world_len = f_lat * FLAT_SCALE / zoom
            flx_w = wx + lat_wx * force_world_len
            fly_w = wy + lat_wy * force_world_len
            pygame.draw.line(surface, (255, 160, 30), (sx, sy),
                             w2s(flx_w, fly_w), 1)

        # grip label
        ts = font.render(f"g{idx}:{grip:.2f}", True, (230, 230, 245))
        surface.blit(ts, (sx + 6, sy - 8))

    # -- text HUD (bottom-left) --
    _, _, dbg_seg, dbg_t, _ = _nearest_on_polyline(
        car.x, car.y, polyline, hint_seg=seg_hint)
    dbg_path_dist = _signed_distance(car.x, car.y, polyline, dbg_seg, dbg_t)
    tang_300_norm, tang_300_ahead, tang_300_seg = _relative_angle_to_path_tangent(
        car.angle, polyline, dbg_seg, dbg_t, LOOKAHEAD_DIST_1)
    tang_600_norm, tang_600_ahead, tang_600_seg = _relative_angle_to_path_tangent(
        car.angle, polyline, dbg_seg, dbg_t, LOOKAHEAD_DIST_2)
    tang_900_norm, tang_900_ahead, tang_900_seg = _relative_angle_to_path_tangent(
        car.angle, polyline, dbg_seg, dbg_t, LOOKAHEAD_DIST_3)
    look_300_x, look_300_y, _, _ = _advance_along_polyline(
        polyline, dbg_seg, dbg_t, LOOKAHEAD_DIST_1)
    look_600_x, look_600_y, _, _ = _advance_along_polyline(
        polyline, dbg_seg, dbg_t, LOOKAHEAD_DIST_2)
    look_900_x, look_900_y, _, _ = _advance_along_polyline(
        polyline, dbg_seg, dbg_t, LOOKAHEAD_DIST_3)

    for look_x, look_y, look_tangent, color in (
        (look_300_x, look_300_y, tang_300_ahead, (120, 220, 255)),
        (look_600_x, look_600_y, tang_600_ahead, (255, 170, 90)),
        (look_900_x, look_900_y, tang_900_ahead, (255, 110, 210)),
    ):
        pt = w2s(look_x, look_y)
        pygame.draw.circle(surface, color, pt, 5, 2)
        tangent_len = 28.0 / zoom
        tx0 = look_x - math.cos(look_tangent) * tangent_len * 0.5
        ty0 = look_y - math.sin(look_tangent) * tangent_len * 0.5
        tx1 = look_x + math.cos(look_tangent) * tangent_len * 0.5
        ty1 = look_y + math.sin(look_tangent) * tangent_len * 0.5
        pygame.draw.line(surface, color, w2s(tx0, ty0), w2s(tx1, ty1), 2)

    fwd_speed = car.vx * ca_c + car.vy * sa_c
    lat_speed = car.vx * (-sa_c) + car.vy * ca_c
    speed = math.hypot(car.vx, car.vy)
    car_type = getattr(car, "car_type", "?")

    info_lines = [
        f"Car: {car_type}",
        f"Speed: {speed:.0f}   fwd: {fwd_speed:.0f}   lat: {lat_speed:.0f}",
        f"Angle: {math.degrees(car.angle):.1f} deg   v_angle: {car.v_angle:.2f}",
        f"Grip: {' '.join(f'{g:.2f}' for g in grips)}",
        f"Path dist: {dbg_path_dist:+.1f}  abs: {abs(dbg_path_dist):.1f}",
        f"Tan +300: {tang_300_norm:+.2f} ({math.degrees(tang_300_ahead):.1f} deg)",
        f"Tan +600: {tang_600_norm:+.2f} ({math.degrees(tang_600_ahead):.1f} deg)",
        f"Tan +900: {tang_900_norm:+.2f} ({math.degrees(tang_900_ahead):.1f} deg)",
        f"Checkpoint hits: {checkpoint_hits}",
    ]
    y_off = H - len(info_lines) * 18 - 6
    for line in info_lines:
        ts = font.render(line, True, (200, 200, 200))
        surface.blit(ts, (6, y_off))
        y_off += 18

    if checkpoint_flash > 0 and last_checkpoint_gain > 0:
        msg = f"CHECKPOINT +{int(CHECKPOINT_REWARD * last_checkpoint_gain)}"
        col = (255, 230, 120) if checkpoint_flash % 6 < 3 else (255, 180, 70)
        ts = font.render(msg, True, col)
        surface.blit(ts, (W // 2 - ts.get_width() // 2, 10))


# === main ===================================================================

def main():
    global MAX_EPISODE_STEPS
    pygame.init()

    map_num = const.MAP_NUM
    polyline, meta = _load_path_polyline(map_num)
    left_edge, right_edge = _build_edge_segments(polyline, half_width=70)

    # Display
    map_w = int(meta.get("width", 2944))
    map_h = int(meta.get("height", 2496))
    scale = 0.4
    win_w, win_h = int(map_w * scale), int(map_h * scale)
    screen = pygame.display.set_mode((win_w, win_h))
    pygame.display.set_caption("NN Trainer  -  Natural Selection")

    # Second window: zoomed physics debug view for the best alive car
    from pygame._sdl2.video import Window as SDLWindow
    debug_win = SDLWindow("Physics Debug", size=(DEBUG_WIN_SIZE, DEBUG_WIN_SIZE))
    debug_surf = pygame.Surface((DEBUG_WIN_SIZE, DEBUG_WIN_SIZE))

    # Environment and GA
    env = TrainingEnv(polyline, meta, POPULATION_SIZE)
    ga = GeneticAlgorithm(POPULATION_SIZE)

    # Attempt to load existing model
    os.makedirs("ai_models", exist_ok=True)
    best_path = os.path.join("ai_models", "best_network.pkl")
    ga.load(best_path)

    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 22)
    quit_req = False

    observations = env.reset()
    _t_start = time.time()

    debug_visible = True
    debug_win_id = debug_win.id

    while True:
        # -- events ----------------------------------------------------------
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                quit_req = True
            elif ev.type == pygame.WINDOWCLOSE:
                # Closing the debug window just hides it; main window quits
                ew = getattr(ev, "window", None)
                ew_id = ew.id if ew is not None and hasattr(ew, "id") else 0
                if ew_id == debug_win_id:
                    debug_visible = False
                    debug_win.hide()
                else:
                    quit_req = True

        if quit_req:
            print("\nSaving and exiting ...")
            ga.save(best_path)
            ga.save(os.path.join("ai_models",
                                 f"final_generation_{ga.generation}.pkl"))
            pygame.quit()
            return

        # -- inference -------------------------------------------------------
        # Determine the best alive car so we can enable its compute_debug
        ranked_for_debug = sorted(range(env.num_cars),
                                  key=lambda i: ga.fitness[i], reverse=True)
        best_alive_idx = -1
        for ri in ranked_for_debug:
            if env.car_alive[ri]:
                best_alive_idx = ri
                break
        env.debug_car_idx = best_alive_idx

        actions = []
        for i in range(env.num_cars):
            if i < len(observations):
                actions.append(ga.population[i].forward(observations[i]))
            else:
                actions.append(np.array([0.0, 0.0, 0.0]))

        # -- physics step ----------------------------------------------------
        observations, rewards, done = env.step(actions)

        # accumulate fitness
        ga.fitness += rewards

        # -- episode end? ----------------------------------------------------
        if done:
            elapsed = time.time() - _t_start
            best_idx = int(np.argmax(ga.fitness))
            avg_fit = float(np.mean(ga.fitness))
            best_fit = float(ga.fitness[best_idx])
            alive_n = sum(env.car_alive)
            sps = env.step_count / max(elapsed, 0.01)
            print(f"Gen {ga.generation:>4d}  |  best {best_fit:>8.1f}  avg {avg_fit:>8.1f}  "
                  f"|  alive {alive_n}/{POPULATION_SIZE}  steps {env.step_count}/{MAX_EPISODE_STEPS}  "
                  f"({sps:.0f} steps/s  {elapsed:.1f}s)", flush=True)

            # If the best AI was still alive at max steps with enough speed,
            # increase the episode length so it can learn to go further.
            best_car = env.cars[best_idx]
            best_fwd = (best_car.vx * math.cos(best_car.angle)
                        + best_car.vy * math.sin(best_car.angle))
            extend_max_steps = (
                env.car_alive[best_idx]
                and env.step_count >= MAX_EPISODE_STEPS
                and best_fwd > 30
            )
            if extend_max_steps:
                MAX_EPISODE_STEPS += 500
                MAX_EPISODE_STEPS = min(MAX_EPISODE_STEPS, 5000)
                ga.mutation_scale *= 0.95
                print(f"  >> Best AI still moving (fwd={best_fwd:.0f})  "
                      f"MAX_EPISODE_STEPS -> {MAX_EPISODE_STEPS}  "
                      f"mutation_scale -> {ga.mutation_scale:.3f}")

            ga.evolve()

            if ga.generation % SAVE_EVERY_GEN == 0:
                ga.save(os.path.join("ai_models",
                                     f"generation_{ga.generation}.pkl"))
            ga.save(best_path)

            # Switch epoch car type only when a sufficient fraction of AIs survive
            # at the end of the episode. If >=50% survive, pick a new car next
            # epoch; otherwise keep the same car so agents can continue learning.
            alive_frac = float(alive_n) / float(env.num_cars) if env.num_cars > 0 else 0.0
            keep_car_type = (alive_frac < 0.5)
            if alive_frac >= 0.5:
                print(f"  Majority survived ({alive_n}/{env.num_cars} -> {alive_frac:.2f}); switching car next epoch")
            else:
                print(f"  Too few survivors ({alive_n}/{env.num_cars} -> {alive_frac:.2f}); keeping car next epoch")
            observations = env.reset(keep_car_type=keep_car_type)
            _t_start = time.time()

        # -- render (lightweight, every 10 steps) ----------------------------
        if env.step_count % 2 == 0:
            screen.fill((25, 30, 35))
            draw_track_outline(screen, left_edge, right_edge, scale)
            draw_poly_checkpoints(screen, env.polyline,
                                  env.poly_checkpoint_segments, scale)

            # Rank cars by current fitness, pick top 20 alive for rendering
            TOP_N = 20
            ranked = sorted(range(env.num_cars),
                            key=lambda i: ga.fitness[i], reverse=True)
            top_set = set()
            for ri in ranked:
                if env.car_alive[ri]:
                    top_set.add(ri)
                if len(top_set) >= TOP_N:
                    break

            draw_cars_simple(screen, env.cars, env.car_alive, scale,
                             only_indices=top_set)

            # Draw raycasts for the #1 car
            if top_set:
                best_alive = ranked[0]
                for ri in ranked:
                    if env.car_alive[ri]:
                        best_alive = ri
                        break
                c = env.cars[best_alive]
                for ra in env.ray_angles_rad:
                    hx, hy, rd, hit = raycast_grid(
                        env.edge_grid, c.x, c.y,
                        c.angle + ra, MAX_RAY_DIST)
                    color = (0, 200, 0) if hit else (80, 80, 80)
                    pygame.draw.line(screen, color,
                                     (int(c.x * scale), int(c.y * scale)),
                                     (int(hx * scale), int(hy * scale)), 1)
                    if hit:
                        pygame.draw.circle(screen, (0, 255, 0),
                                           (int(hx * scale), int(hy * scale)), 2)

            # HUD (top-left)
            hud_lines = [
                f"Gen {ga.generation}   Step {env.step_count}/{MAX_EPISODE_STEPS}",
                f"Alive {sum(env.car_alive)}/{POPULATION_SIZE}",
                f"Best fitness (all time): {ga.best_fitness:.1f}",
            ]
            for i, txt in enumerate(hud_lines):
                surf = font.render(txt, True, (220, 220, 220))
                screen.blit(surf, (8, 6 + i * 20))

            # Scoreboard (top-right)
            sb_x = win_w - 195
            sb_y = 6
            header = font.render("-- Top 20 --", True, (255, 220, 80))
            screen.blit(header, (sb_x, sb_y))
            sb_y += 20
            for rank, ri in enumerate(ranked[:TOP_N]):
                alive_tag = "" if env.car_alive[ri] else " X"
                line = f"{rank+1:>2}. #{ri:<3d} {ga.fitness[ri]:>8.1f}{alive_tag}"
                col = (180, 255, 180) if env.car_alive[ri] else (120, 120, 120)
                surf = font.render(line, True, col)
                screen.blit(surf, (sb_x, sb_y))
                sb_y += 16

            pygame.display.flip()

            # -- debug window: zoomed physics view of the best car ----------
            if debug_visible:
                if best_alive_idx >= 0 and env.car_alive[best_alive_idx]:
                    bc = env.cars[best_alive_idx]
                    seg_h = env.car_prev_seg[best_alive_idx]
                    draw_debug_view(debug_surf, bc, env.edge_segments,
                                    env.ray_angles_rad, env.edge_grid,
                                    polyline, seg_h, left_edge, right_edge,
                                    checkpoint_segments=env.poly_checkpoint_segments,
                                    next_checkpoint_idx=env.car_next_checkpoint[best_alive_idx],
                                    checkpoint_hits=env.car_checkpoint_hits[best_alive_idx],
                                    checkpoint_flash=env.car_checkpoint_flash[best_alive_idx],
                                    last_checkpoint_gain=env.car_last_checkpoint_gain[best_alive_idx])
                else:
                    debug_surf.fill((20, 22, 28))
                    msg = _debug_font or pygame.font.Font(None, 18)
                    ts = msg.render("No alive car", True, (120, 120, 120))
                    debug_surf.blit(ts, (DEBUG_WIN_SIZE // 2 - ts.get_width() // 2,
                                         DEBUG_WIN_SIZE // 2))
                debug_win.get_surface().blit(debug_surf, (0, 0))
                debug_win.flip()


if __name__ == "__main__":
    main()
