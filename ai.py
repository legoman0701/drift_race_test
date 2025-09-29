import math
import pygame
from typing import List, Tuple, Optional, Dict, Any

from helpers import clamp


def ai_algorithme(
    path_poly: List[Tuple[float, float]],
    my_car,
    ai_path_mode= False,
    surface = None,
    font_small = None,
):
    """
    Compute basic steering/throttle/brake to follow a polyline path.
    If ai_path_mode and surface are provided, also draw debug visuals and
    return (controls, surface).
    """
    # Optional debug drawing when a surface is provided
    if ai_path_mode and surface is not None:
        surface.fill((0, 0, 0, 0))
        if path_poly:
            pygame.draw.polygon(surface, (255, 0, 0), path_poly, 3)

    if path_poly:
        def _proj_point_on_segment(px, py, ax, ay, bx, by):
            vx, vy = bx - ax, by - ay
            wx, wy = px - ax, py - ay
            denom = vx * vx + vy * vy
            if denom == 0:
                return (ax, ay), 0.0
            t = (wx * vx + wy * vy) / denom
            t_clamped = max(0.0, min(1.0, t))
            return (ax + vx * t_clamped, ay + vy * t_clamped), t_clamped

        px, py = my_car.x, my_car.y
        best_pt = None
        best_d2 = float("inf")
        best_idx = 0
        best_t = 0.0

        for i in range(len(path_poly) - 1):
            (ax, ay), (bx, by) = path_poly[i], path_poly[i + 1]
            (cx, cy), t = _proj_point_on_segment(px, py, ax, ay, bx, by)
            dx, dy = px - cx, py - cy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best_pt = (cx, cy)
                best_idx = i
                best_t = t

        if best_pt is not None:
            cx, cy = best_pt

            # NUDGE forward along path
            NUDGE_UNITS = 250.0

            dist_to_path = math.sqrt(best_d2)
            remaining = max(0.0, NUDGE_UNITS - dist_to_path * 1.2)
            seg_idx = best_idx
            t_on_seg = min(max(best_t, 0.0), 0.999999)

            while remaining > 0:
                if seg_idx >= len(path_poly) - 1:
                    seg_idx = 0
                    t_on_seg = 0.0
                a = path_poly[seg_idx]
                b = path_poly[seg_idx + 1]
                vx, vy = b[0] - a[0], b[1] - a[1]
                seg_len = math.hypot(vx, vy)
                if seg_len == 0:
                    seg_idx += 1
                    t_on_seg = 0.0
                    continue
                dist_to_end = (1.0 - t_on_seg) * seg_len
                if remaining <= dist_to_end + 1e-6:
                    frac = (t_on_seg * seg_len + remaining) / seg_len
                    cx = a[0] + vx * frac
                    cy = a[1] + vy * frac
                    remaining = 0.0
                else:
                    remaining -= dist_to_end
                    seg_idx += 1
                    t_on_seg = 0.0
                    cx, cy = b[0], b[1]

            vx, vy = cx - px, cy - py
            angle_to_point = math.atan2(vy, vx)
            car_angle = my_car.angle
            angle_diff = ((angle_to_point - car_angle + math.pi) % (2 * math.pi)) - math.pi
            angle_deg = math.degrees(angle_diff)

            if ai_path_mode and surface is not None:
                pygame.draw.circle(surface, (0, 255, 0), (int(cx), int(cy)), 6)
                pygame.draw.line(surface, (0, 255, 0), (int(px), int(py)), (int(cx), int(cy)), 2)
                hx, hy = px + math.cos(car_angle) * 40, py + math.sin(car_angle) * 40
                pygame.draw.line(surface, (0, 0, 255), (int(px), int(py)), (int(hx), int(hy)), 2)
                pygame.draw.line(surface, (0, 255, 0), (int(px), int(py)), (int(cx), int(cy)), 2)
                if font_small is not None:
                    lbl = font_small.render(f"{angle_deg:+.1f}°", True, (255, 255, 255))
                    surface.blit(lbl, (int(px + 8), int(py - 22)))
                # Mark the segment start
                sa = path_poly[best_idx]
                pygame.draw.circle(surface, (255, 255, 0), (int(sa[0]), int(sa[1])), 4)

            st = angle_diff * 2
            th = 1 - clamp(abs(angle_diff) * 0.5, 0, 1) + 0.1
            br = clamp(abs(angle_diff) * 0.25, 0, 1)
            if ai_path_mode and surface is not None:
                return {"th": th, "st": st, "br": br}, surface
            return {"th": th, "st": st, "br": br}

    # default gentle forward if no path
    return {"th": 0.1, "st": 0.0, "br": 0.0}
