import math, pygame, os, pickle
from typing import List, Tuple, Optional, Dict
from drift.core.helpers import clamp
import drift.config.const as const

# Neural-network based AI (replacement for polyline follower)
try:
    import tools.nn_trainer as nn_trainer
    import numpy as np
except Exception:
    # Try adding project root to sys.path and retry (allows importing top-level tools/)
    try:
        import sys
        _ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        if _ROOT not in sys.path:
            sys.path.insert(0, _ROOT)
        import tools.nn_trainer as nn_trainer
        import numpy as np
    except Exception:
        nn_trainer = None
        np = None

# Module-level cached NN and spatial grids keyed by path id
_NN_MODEL = None
_NN_LOADED = False
_GRID_CACHE = {}

def _load_nn_model():
    global _NN_MODEL, _NN_LOADED
    if _NN_LOADED:
        return
    _NN_LOADED = True
    if nn_trainer is None:
        _NN_MODEL = None
        return
    best_path = os.path.join("ai_models", "generation_135.pkl")
    try:
        if os.path.exists(best_path):
            with open(best_path, "rb") as f:
                d = pickle.load(f)
            arch = d.get("arch") or d.get("architecture", {})
            in_s = arch.get("in") or nn_trainer.INPUT_SIZE
            hid = arch.get("hidden") or list(nn_trainer.HIDDEN_SIZES)
            out_s = arch.get("out") or nn_trainer.OUTPUT_SIZE
            net = nn_trainer.NeuralNetwork(in_s, list(hid), out_s)
            net.set_weights(d["weights"])
            _NN_MODEL = net
            print(f"[ai.nn] loaded NN model from {best_path} with architecture {in_s}-{hid}-{out_s}")
            return
    except Exception as e:
        print("[ai.nn] failed to load NN model:", e)
    # fallback: fresh random net
    try:
        _NN_MODEL = nn_trainer.NeuralNetwork()
        print("[ai.nn] using fresh random NN model as fallback")
    except Exception:
        _NN_MODEL = None


def ai_algorithme(
    path_poly: List[Tuple[float, float]],
    my_car,
    ai_path_mode: bool = False,
    surface: Optional[pygame.Surface] = None,
    font_small: Optional[pygame.font.Font] = None,
) -> Dict[str, float] | tuple[Dict[str, float], pygame.Surface]:
    """
    Compute basic steering/throttle/brake to follow a polyline path.
    If ai_path_mode and surface are provided, also draw debug visuals and
    return (controls, surface).
    """
    # Try to load NN model lazily
    _load_nn_model()

    # Debug surface setup: when AI Path Mode is active always prepare
    # the debug surface (user requested full NN debug when ai_path_mode).
    if ai_path_mode and surface is not None:
        surface.fill((0, 0, 0, 0))
        if path_poly:
            try:
                pygame.draw.polygon(surface, (255, 0, 0), path_poly, 3)
            except Exception:
                pass

    # If NN infrastructure is not available or no path, fall back to poly follower
    if nn_trainer is None or _NN_MODEL is None or not path_poly:
        # Fallback: original polyline follower
        # (kept verbatim to preserve previous behaviour when NN not present)
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
                    try:
                        pygame.draw.circle(surface, (0, 255, 0), (int(cx), int(cy)), 6)
                        pygame.draw.line(surface, (0, 255, 0), (int(px), int(py)), (int(cx), int(cy)), 2)
                        hx, hy = px + math.cos(car_angle) * 40, py + math.sin(car_angle) * 40
                        pygame.draw.line(surface, (0, 0, 255), (int(px), int(py)), (int(hx), int(hy)), 2)
                        pygame.draw.line(surface, (0, 255, 0), (int(px), int(py)), (int(cx), int(cy)), 2)
                        if font_small is not None:
                            lbl = font_small.render(f"{angle_deg:+.1f}°", True, (255, 255, 255))
                            surface.blit(lbl, (int(px + 8), int(py - 22)))
                        sa = path_poly[best_idx]
                        pygame.draw.circle(surface, (255, 255, 0), (int(sa[0]), int(sa[1])), 4)
                        # controls text
                        try:
                            txt = f"th={th:+.2f} st={st:+.2f} br={br:+.2f}"
                            if font_small is not None:
                                surf_txt = font_small.render(txt, True, (240, 240, 240))
                                surface.blit(surf_txt, (8, 8))
                        except Exception:
                            pass
                    except Exception:
                        pass

                my_car.target_angle = angle_to_point
                speed = math.hypot(my_car.vx, my_car.vy)
                th = 1 - clamp(abs(angle_diff) * speed / 240, 0, 1) + 0.1
                th = clamp(th, 0.0, 1.0)
                br = clamp(abs(angle_diff) * speed / 240 - 0.2, 0, 1)

                # Compute a raw steering command so fallback drives toward the target.
                # Map angular error to steering in [-1,1]. Mirror human controller scaling.
                fwd_x, fwd_y = math.cos(car_angle), math.sin(car_angle)
                body_fwd = my_car.vx * fwd_x + my_car.vy * fwd_y
                dir_sign = math.copysign(1.0, body_fwd) if abs(body_fwd) > 1e-3 else 1.0
                st = clamp(angle_diff * 2.0, -1.0, 1.0) * dir_sign

                if ai_path_mode and surface is not None:
                    return {"th": th, "st": float(st), "br": br}, surface
                return {"th": th, "st": float(st), "br": br}
        return {"th": 0.1, "st": 0.0, "br": 0.0}

    # --- Neural-network branch -------------------------------------------------
    try:
        # Nearest on polyline (for signed distance, segment index and t)
        cx, cy, seg, t, d2 = nn_trainer._nearest_on_polyline(my_car.x, my_car.y, path_poly, hint_seg=0)
        dist_from_path = nn_trainer._signed_distance(my_car.x, my_car.y, path_poly, seg, t)
        dist_norm = clamp(dist_from_path / 160.0, -1.0, 1.0)

        # angle difference to tangent (normalized)
        angle_norm = clamp(nn_trainer._relative_angle_to_path_tangent(my_car.angle, path_poly, seg, t, nn_trainer.LOOKAHEAD_DIST_1) * nn_trainer.SIM_DT / nn_trainer.ANGVEL_NORM_FRAME, -1.0, 1.0)

        # Build/cached edge grid for raycasts
        poly_key = id(path_poly)
        grid = _GRID_CACHE.get(poly_key)
        if grid is None:
            left_edge, right_edge = nn_trainer._build_edge_segments(path_poly, half_width=70)
            segs = nn_trainer._segments_from_polyline(left_edge) + nn_trainer._segments_from_polyline(right_edge)
            grid = nn_trainer.SegmentGrid(segs, cell=120.0)
            _GRID_CACHE[poly_key] = grid

        # Raycasts
        rays = []
        ray_hits = []
        for ra in nn_trainer.RAYCAST_ANGLES_DEG:
            # convert deg list to radians on-the-fly
            rad = math.radians(ra)
            hx, hy, rd, hit = nn_trainer.raycast_grid(grid, my_car.x, my_car.y, my_car.angle + rad, nn_trainer.MAX_RAY_DIST)
            rays.append(rd / nn_trainer.MAX_RAY_DIST if hit else 1.0)
            ray_hits.append((hx, hy, hit))

        ib_val = 1.0 if math.sqrt(d2) < 70.0 else 0.0

        # tangents ahead
        tang_300 = nn_trainer._relative_angle_to_path_tangent(my_car.angle, path_poly, seg, t, nn_trainer.LOOKAHEAD_DIST_1)
        tang_600 = nn_trainer._relative_angle_to_path_tangent(my_car.angle, path_poly, seg, t, nn_trainer.LOOKAHEAD_DIST_2)
        tang_900 = nn_trainer._relative_angle_to_path_tangent(my_car.angle, path_poly, seg, t, nn_trainer.LOOKAHEAD_DIST_3)
        tang_300_norm = clamp(tang_300 * nn_trainer.SIM_DT / nn_trainer.ANGVEL_NORM_FRAME, -1.0, 1.0)
        tang_600_norm = clamp(tang_600 * nn_trainer.SIM_DT / nn_trainer.ANGVEL_NORM_FRAME, -1.0, 1.0)
        tang_900_norm = clamp(tang_900 * nn_trainer.SIM_DT / nn_trainer.ANGVEL_NORM_FRAME, -1.0, 1.0)

        # body-frame velocities
        fwd_x, fwd_y = math.cos(my_car.angle), math.sin(my_car.angle)
        rgt_x, rgt_y = -fwd_y, fwd_x
        fwd_vel = (my_car.vx * fwd_x + my_car.vy * fwd_y) * nn_trainer.SIM_DT / nn_trainer.SPEED_NORM_FRAME
        lat_vel = (my_car.vx * rgt_x + my_car.vy * rgt_y) * nn_trainer.SIM_DT / nn_trainer.SPEED_NORM_FRAME
        ang_vel = clamp(my_car.v_angle * nn_trainer.SIM_DT / nn_trainer.ANGVEL_NORM_FRAME, -1.0, 1.0)
        abs_vel = math.hypot(my_car.vx, my_car.vy) * nn_trainer.SIM_DT / nn_trainer.SPEED_NORM_FRAME

        grip = getattr(my_car, "has_grip", (1.0, 1.0, 1.0, 1.0))

        # car spec inputs
        spec_in = nn_trainer._car_spec_inputs(getattr(my_car, "specs", {}))

        obs = np.array([
            fwd_vel,
            lat_vel,
            ang_vel,
            abs_vel,
            grip[0], grip[1], grip[2], grip[3],
            dist_norm,
            angle_norm,
            *rays,
            ib_val,
            tang_300_norm, tang_600_norm, tang_900_norm,
            *spec_in,
        ], dtype=np.float32)

        out = _NN_MODEL.forward(obs)
        controls = {"th": float(out[0]), "st": float(out[1]), "br": float(out[2])}
        # Draw debug overlays when ai_path_mode requested (always draw for AI Path Mode)
        if ai_path_mode and surface is not None:
            try:
                pygame.draw.circle(surface, (0, 255, 0), (int(cx), int(cy)), 4)
                pygame.draw.line(surface, (0, 255, 0), (int(my_car.x), int(my_car.y)), (int(cx), int(cy)), 2)
                hx2, hy2 = my_car.x + math.cos(my_car.angle) * 40, my_car.y + math.sin(my_car.angle) * 40
                pygame.draw.line(surface, (0, 0, 255), (int(my_car.x), int(my_car.y)), (int(hx2), int(hy2)), 2)
                for (hx, hy, hit) in ray_hits:
                    col = (0, 220, 0) if hit else (80, 80, 80)
                    pygame.draw.line(surface, col, (int(my_car.x), int(my_car.y)), (int(hx), int(hy)), 1)
                if font_small is not None:
                    try:
                        txt = f"th={controls['th']:+.2f} st={controls['st']:+.2f} br={controls['br']:+.2f}"
                        surf_txt = font_small.render(txt, True, (240, 240, 240))
                        surface.blit(surf_txt, (8, 8))
                    except Exception:
                        pass
            except Exception:
                pass
        return (controls, surface) if (ai_path_mode and surface is not None) else controls
    except Exception:
        # If anything goes wrong, fall back to simple forward
        return {"th": 0.1, "st": 0.0, "br": 0.0}
