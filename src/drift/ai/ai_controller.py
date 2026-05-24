import math
import random
from typing import Any, Dict

from drift.core.helpers import clamp
from drift.ai.ai_difficulty import get_profile
from drift.ai.learned import apply_learned_controls


def _extract_path(path_data: Any):
    if isinstance(path_data, list):
        return path_data, None, 1
    if isinstance(path_data, dict):
        poly = path_data.get("polyline", []) or []
        traj = path_data.get("trajectory", []) or None
        map_num = int(path_data.get("map_num", 1))
        return poly, traj, map_num
    return [], None, 1


def _closest_index_on_poly(poly, px, py):
    best_idx = 0
    best_d2 = float("inf")
    for i, (x, y) in enumerate(poly):
        d2 = (x - px) ** 2 + (y - py) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_idx = i
    return best_idx


def _lookahead_target(poly, idx, lookahead):
    n = len(poly)
    i = idx
    remaining = lookahead
    tx, ty = poly[i]
    while remaining > 0 and n > 1:
        j = (i + 1) % n
        ax, ay = poly[i]
        bx, by = poly[j]
        seg = math.hypot(bx - ax, by - ay)
        if seg < 1e-6:
            i = j
            continue
        if remaining <= seg:
            t = remaining / seg
            tx = ax + (bx - ax) * t
            ty = ay + (by - ay) * t
            break
        remaining -= seg
        i = j
        tx, ty = bx, by
    return tx, ty, i


def _smooth_controls(car, controls: Dict[str, float], reaction_delay: float) -> Dict[str, float]:
    if reaction_delay <= 0.0:
        return controls

    prev = getattr(car, "_ai_prev_controls", None)
    if prev is None:
        car._ai_prev_controls = dict(controls)
        return controls

    alpha = clamp(1.0 - reaction_delay, 0.2, 1.0)
    out = {
        "th": prev["th"] * (1.0 - alpha) + controls["th"] * alpha,
        "st": prev["st"] * (1.0 - alpha) + controls["st"] * alpha,
        "br": prev["br"] * (1.0 - alpha) + controls["br"] * alpha,
    }
    car._ai_prev_controls = out
    return out


def compute_path_controls(
    path_data: Any,
    car,
    difficulty: str = "medium",
    use_learned: bool = False,
) -> Dict[str, float]:
    profile = get_profile(difficulty)
    poly, traj, map_num = _extract_path(path_data)

    if not poly:
        return {"th": 0.1, "st": 0.0, "br": 0.0}

    px, py = car.x, car.y
    idx = _closest_index_on_poly(poly, px, py)
    speed = math.hypot(car.vx, car.vy)

    lookahead = clamp((120.0 + speed * 0.55) * profile.lookahead_scale, 80.0, 380.0)
    tx, ty, i = _lookahead_target(poly, idx, lookahead)

    angle_to_target = math.atan2(ty - py, tx - px)
    if profile.steering_noise > 0:
        angle_to_target += random.uniform(-profile.steering_noise, profile.steering_noise)

    car.target_angle = angle_to_target
    angle_diff = ((angle_to_target - car.angle + math.pi) % (2 * math.pi)) - math.pi

    kappa = 0.0
    v_ref = 180.0
    drift_zone = False
    drift_intensity = 0.0

    if traj:
        p = traj[i % len(traj)]
        kappa = float(p.get("kappa", 0.0))
        v_ref = float(p.get("v_target", 180.0)) * profile.speed_scale
        drift_zone = bool(p.get("drift_zone", False))
        drift_intensity = float(p.get("drift_intensity", 0.0))
    else:
        v_ref = 180.0 - min(120.0, abs(math.degrees(angle_diff)) * 1.2)
        v_ref = clamp(v_ref, 60.0, 240.0) * profile.speed_scale

    over_speed = speed - v_ref
    steer_penalty = clamp(abs(angle_diff) * 1.2, 0.0, 1.0)

    th = clamp((0.85 - steer_penalty * 0.55 - abs(kappa) * 0.45) * profile.throttle_scale, 0.05, 1.0)
    br = clamp((abs(kappa) * 0.15) * profile.brake_scale, 0.0, 0.35)

    if over_speed > 0:
        excess_ratio = clamp(over_speed / max(v_ref, 1.0), 0.0, 1.0)
        th = clamp(th * (1.0 - excess_ratio), 0.0, 1.0)
        # br is intentionally NOT overridden here; the kappa-based br above is sufficient.
        # Setting br high (handbrake/wheel-lock) overwhelms the engine force and prevents
        # the car from accelerating at all: lock_strength * speed >> engine force.

    if drift_zone:
        drift_error = profile.drift_target - car.drift_ratio
        if drift_error > 0.05:
            br = max(br, profile.drift_brake_boost * drift_intensity)
            th = max(th, 0.55 * profile.throttle_scale)
        elif drift_error < -0.20:
            br *= 0.5
            th *= 0.75

    controls = {"th": th, "st": 0.0, "br": br}

    if use_learned:
        controls = apply_learned_controls(
            car=car,
            base_controls=controls,
            map_num=map_num,
            difficulty=difficulty,
        )

    return _smooth_controls(car, controls, profile.reaction_delay)