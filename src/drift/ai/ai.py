import math
import pygame
from typing import Any, Dict, Optional

import drift.config.const as const
from drift.ai.ai_controller import compute_path_controls


def _extract_poly(path_data: Any):
    if isinstance(path_data, list):
        return path_data
    if isinstance(path_data, dict):
        return path_data.get("polyline", []) or []
    return []


def _path_is_ready(path_data: Any) -> bool:
    if isinstance(path_data, dict):
        return len(path_data.get("polyline", []) or []) > 0
    if isinstance(path_data, list):
        return len(path_data) > 0
    return False


def ai_algorithme(
    path_poly: Any,
    my_car,
    ai_path_mode: bool = False,
    surface: Optional[pygame.Surface] = None,
    font_small: Optional[pygame.font.Font] = None,
    difficulty: Optional[str] = None,
) -> Dict[str, float] | tuple[Dict[str, float], pygame.Surface]:
    level = difficulty or getattr(my_car, "ai_difficulty", getattr(const, "AI_DIFFICULTY", "medium"))
    use_learned = bool(getattr(const, "AI_USE_LEARNED", False))

    if not _path_is_ready(path_poly):
        return {"th": 0.1, "st": 0.0, "br": 0.0}

    poly = _extract_poly(path_poly)

    if ai_path_mode and const.DEBUG and surface is not None and poly:
        surface.fill((0, 0, 0, 0))
        pygame.draw.polygon(surface, (255, 0, 0), [(int(x), int(y)) for x, y in poly], 2)

    controls = compute_path_controls(path_poly, my_car, difficulty=level, use_learned=use_learned)

    if ai_path_mode and const.DEBUG and surface is not None and poly:
        px, py = my_car.x, my_car.y
        speed = math.hypot(my_car.vx, my_car.vy)
        traj_ok = isinstance(path_poly, dict) and bool(path_poly.get("trajectory"))
        if font_small is not None:
            txt = font_small.render(
                f"{level} v={speed:.1f} th={controls['th']:.2f} br={controls['br']:.2f} traj={traj_ok}",
                True, (255, 255, 255),
            )
            surface.blit(txt, (int(px + 10), int(py - 20)))
        return controls, surface

    return controls