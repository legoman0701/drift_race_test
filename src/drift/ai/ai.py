import math, pygame
from typing import List, Tuple, Optional, Dict
from drift.core.helpers import clamp
from drift.ai.drift_ai import DriftAI
import drift.config.const as const

# Phase -> colour mapping for debug visuals
_PHASE_COLORS = {
    "grip":     (0, 200, 0),
    "initiate": (255, 200, 0),
    "drift":    (255, 80, 0),
    "recover":  (255, 0, 0),
}


def _ensure_drift_ai(car):
    """Lazily attach a DriftAI controller to a car instance."""
    ctrl = getattr(car, "_drift_ai", None)
    if ctrl is None:
        ctrl = DriftAI()
        car._drift_ai = ctrl
    return ctrl


def ai_algorithme(
    path_poly: List[Tuple[float, float]],
    my_car,
    dt: float = 1.0 / 60.0,
    ai_path_mode: bool = False,
    surface: Optional[pygame.Surface] = None,
    font_small: Optional[pygame.font.Font] = None,
) -> Dict[str, float] | tuple[Dict[str, float], pygame.Surface]:
    """
    PID-based drift AI that outputs raw (th, st, br) controls through
    the same pipeline as the player.  No direct target_angle writes.
    """
    draw_debug = (ai_path_mode or const.AI_DEBUG) and surface is not None
    if draw_debug:
        surface.fill((0, 0, 0, 0))
        # Draw path polyline
        if path_poly and len(path_poly) >= 2:
            pts = [(int(p[0]), int(p[1])) for p in path_poly]
            pygame.draw.lines(surface, (255, 0, 0, 120), True, pts, 2)

    if path_poly and len(path_poly) >= 3:
        ctrl = _ensure_drift_ai(my_car)
        controls = ctrl.compute(path_poly, my_car, dt)

        if draw_debug:
            _draw_ai_debug(surface, my_car, ctrl, controls, font_small)

        if (ai_path_mode or const.AI_DEBUG) and surface is not None:
            return controls, surface
        return controls

    # default gentle forward if no path
    return {"th": 0.1, "st": 0.0, "br": 0.0}


# --------------------------------------------------------------------------
#  Full AI debug overlay (toggled with F6 via const.AI_DEBUG)
# --------------------------------------------------------------------------

def _draw_ai_debug(surface, car, ctrl, controls, font_small):
    """Draw comprehensive AI debug visualisations onto the world-space surface."""
    d = ctrl.dbg
    px, py = car.x, car.y
    ipx, ipy = int(px), int(py)
    angle = car.angle
    phase_col = _PHASE_COLORS.get(ctrl.phase, (200, 200, 200))

    # ---- 1. Heading arrow (blue) ----
    hx = px + math.cos(angle) * 50
    hy = py + math.sin(angle) * 50
    pygame.draw.line(surface, (60, 120, 255), (ipx, ipy), (int(hx), int(hy)), 2)

    # ---- 2. Velocity arrow (orange) ----
    speed = d["speed"]
    if speed > 1.0:
        vscale = 50.0 / speed
        vex = px + car.vx * vscale
        vey = py + car.vy * vscale
        pygame.draw.line(surface, (255, 160, 0), (ipx, ipy), (int(vex), int(vey)), 2)

    # ---- 3. Path tangent arrow at lookahead (cyan) ----
    ta = d["tan_angle"]
    tax = d["la_x"] + math.cos(ta) * 30
    tay = d["la_y"] + math.sin(ta) * 30
    pygame.draw.line(surface, (0, 220, 220),
                     (int(d["la_x"]), int(d["la_y"])),
                     (int(tax), int(tay)), 2)

    # ---- 4. Desired heading arrow from car (phase colour) ----
    if ctrl.phase in ("drift", "initiate"):
        dh = ta + ctrl.drift_direction * ctrl.active_drift_angle
        dhx = px + math.cos(dh) * 45
        dhy = py + math.sin(dh) * 45
        pygame.draw.line(surface, phase_col, (ipx, ipy), (int(dhx), int(dhy)), 2)

    # ---- 5. Nearest point on path (white cross) ----
    nx, ny = int(d["near_x"]), int(d["near_y"])
    pygame.draw.line(surface, (255, 255, 255), (nx - 4, ny), (nx + 4, ny), 1)
    pygame.draw.line(surface, (255, 255, 255), (nx, ny - 4), (nx, ny + 4), 1)

    # ---- 6. Lateral error line (car -> nearest, magenta) ----
    pygame.draw.line(surface, (255, 0, 255), (ipx, ipy), (nx, ny), 1)

    # ---- 7. Lookahead points ----
    # Short (small white dot)
    pygame.draw.circle(surface, (200, 200, 200),
                       (int(d["la_short_x"]), int(d["la_short_y"])), 3)
    # Primary (green dot)
    pygame.draw.circle(surface, (0, 255, 0),
                       (int(d["la_x"]), int(d["la_y"])), 5)
    # Far / curvature (yellow dot)
    pygame.draw.circle(surface, (255, 255, 0),
                       (int(d["la_far_x"]), int(d["la_far_y"])), 4)

    # Lines from car to lookahead targets
    pygame.draw.line(surface, (0, 255, 0, 100), (ipx, ipy),
                     (int(d["la_x"]), int(d["la_y"])), 1)
    pygame.draw.line(surface, (255, 255, 0, 100), (ipx, ipy),
                     (int(d["la_far_x"]), int(d["la_far_y"])), 1)

    # ---- 8. Track width markers at nearest point ----
    tw = d["seg_width"] * 0.5
    perp_x = -math.sin(ta)
    perp_y = math.cos(ta)
    lx1 = d["near_x"] + perp_x * tw
    ly1 = d["near_y"] + perp_y * tw
    lx2 = d["near_x"] - perp_x * tw
    ly2 = d["near_y"] - perp_y * tw
    pygame.draw.line(surface, (100, 100, 100), (int(lx1), int(ly1)),
                     (int(lx2), int(ly2)), 1)

    # ---- 9. Phase ring around car ----
    pygame.draw.circle(surface, phase_col, (ipx, ipy), 18, 2)

    # ---- 10. Handbrake tap indicator (bright red flash) ----
    if ctrl._hb_tap_active:
        pygame.draw.circle(surface, (255, 0, 0), (ipx, ipy - 25), 5)

    # ---- 11. Text HUD near car ----
    if font_small is not None:
        slip_deg = math.degrees(d["slip_angle"])
        ada_deg = math.degrees(ctrl.active_drift_angle)
        curv = d["curvature"]
        lat_err = d["signed_perp_dist"]
        c = controls

        lines = [
            f"Phase: {ctrl.phase}  dir={ctrl.drift_direction:+d}",
            f"Slip: {slip_deg:+.1f}  target: {ada_deg:.1f}",
            f"Yaw: {d['angular_vel']:+.2f} rad/s",
            f"Curv: {curv:.5f}  Lat: {lat_err:+.0f}",
            f"Speed: {speed:.0f}  DT: {ctrl._drivetrain or '?'}",
            f"TH={c['th']:+.2f}  ST={c['st']:+.2f}  HB={c['br']:.2f}",
        ]
        if ctrl._hb_tap_active:
            lines.append(f"** HB TAP ** t={ctrl._hb_tap_timer:.3f}")

        for i, txt in enumerate(lines):
            lbl = font_small.render(txt, True, (255, 255, 255))
            surface.blit(lbl, (ipx + 22, ipy - 40 + i * 14))
