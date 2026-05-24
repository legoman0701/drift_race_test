import os
import pickle
from typing import Dict, Optional

import numpy as np

from drift.tools.paths import asset_path
from drift.core.helpers import clamp

_cache: Dict[str, object] = {}


class _LoadedPolicy:
    def __init__(self, network, track_mask):
        self.network = network
        self.track_mask = track_mask


def _load_network_from_pkl(path: str):
    with open(path, "rb") as fh:
        data = pickle.load(fh)

    # Import training classes from tests/ai_env.py
    from tests.ai_env import NeuralNetwork

    arch = data["architecture"]
    net = NeuralNetwork(arch["input_size"], arch["hidden_sizes"], arch["output_size"])
    net.set_weights(data["weights"])
    return net


def _build_track_mask(map_num: int):
    import pygame
    from tests.ai_env import create_black_mask
    from drift.tools.paths import normalize_asset_path

    ring_path = normalize_asset_path("track", f"map{map_num}", "ring.png")
    ring_img = pygame.image.load(ring_path).convert()
    return create_black_mask(ring_img)


def get_policy(map_num: int, difficulty: str) -> Optional[_LoadedPolicy]:
    key = f"map{map_num}_{difficulty}"
    if key in _cache:
        return _cache[key]

    model_path = asset_path("ai_models", f"{key}.pkl")
    if not os.path.exists(model_path):
        return None

    try:
        net = _load_network_from_pkl(str(model_path))
        mask = _build_track_mask(map_num)
        policy = _LoadedPolicy(net, mask)
        _cache[key] = policy
        return policy
    except Exception as e:
        print(f"[AI] Failed to load learned policy {model_path}: {e}")
        return None


def _observation_from_car(car, track_mask) -> np.ndarray:
    import math
    from tests.ai_env import raycast_black_mask

    forward_v = (car.vx * math.cos(car.angle) + car.vy * math.sin(car.angle)) / 1000.0
    lateral_v = (-car.vx * math.sin(car.angle) + car.vy * math.cos(car.angle)) / 1000.0

    state = [
        clamp(forward_v, -1.0, 1.0),
        clamp(lateral_v, -1.0, 1.0),
        clamp(car.drift_ratio, 0.0, 1.0),
        clamp(car.v_angle / 100.0, -1.0, 1.0),
    ]

    ray_angles_deg = [-80, -40, -20, -10, -5, 0, 5, 10, 20, 40, 80]
    max_dist = 400.0
    rays = []
    for deg in ray_angles_deg:
        _, _, dist, hit = raycast_black_mask(
            track_mask,
            car.x * 0.5,
            car.y * 0.5,
            car.angle + math.radians(deg),
            max_dist,
        )
        rays.append(dist / max_dist if hit else 1.0)

    return np.array(state + rays, dtype=np.float32)


def apply_learned_controls(
    car,
    base_controls: Dict[str, float],
    map_num: int,
    difficulty: str,
) -> Dict[str, float]:
    policy = get_policy(map_num, difficulty)
    if policy is None:
        return base_controls

    obs = _observation_from_car(car, policy.track_mask)
    action = policy.network.forward(obs)

    learned = {
        "th": clamp(float(action[0]), 0.0, 1.0),
        "st": clamp(float(action[1]), -1.0, 1.0),
        "br": clamp(float(action[2]), 0.0, 1.0),
    }

    # Hybrid: path for steering intent, learned for throttle/brake/drift
    return {
        "th": clamp(0.35 * base_controls["th"] + 0.65 * learned["th"], 0.0, 1.0),
        "st": learned["st"],
        "br": clamp(0.35 * base_controls["br"] + 0.65 * learned["br"], 0.0, 1.0),
    }