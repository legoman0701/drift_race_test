import math
import json
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw
import numpy as np

from drift.tools.paths import normalize_asset_path

_executor = ThreadPoolExecutor(max_workers=1)


def _load_map_meta_for_map(map_path: str) -> dict:
    p = normalize_asset_path(map_path)
    meta_path = p.parent / "map_meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _build_driveable_mask(map_path: str, meta: dict) -> np.ndarray:
    img = Image.open(normalize_asset_path(map_path)).convert("RGB")
    arr = np.asarray(img, dtype=np.uint8)
    driveable = arr[:, :, 1] < 170

    mesh = meta.get("collision_mesh", []) or []
    if mesh:
        h, w = driveable.shape
        mask_img = Image.new("L", (w, h), 255)
        draw = ImageDraw.Draw(mask_img)
        for poly in mesh:
            if len(poly) >= 3:
                draw.polygon([tuple(p) for p in poly], fill=0)
        barrier_mask = np.asarray(mask_img, dtype=np.uint8) > 0
        driveable &= barrier_mask

    return driveable


def _ordered_checkpoint_centers(meta: dict):
    cps = meta.get("checkpoints", []) or []
    if not cps:
        return []
    cps_sorted = sorted(cps, key=lambda c: int(c.get("id", 0)))
    centers = []
    for c in cps_sorted:
        x = float(c["x"]) + float(c["width"]) * 0.5
        y = float(c["y"]) + float(c["height"]) * 0.5
        centers.append((x, y))
    return centers


def _densify_closed_polyline(points, step=20.0):
    if len(points) < 2:
        return points[:]
    dense = []
    n = len(points)
    for i in range(n):
        ax, ay = points[i]
        bx, by = points[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        if seg < 1e-6:
            continue
        k = max(1, int(seg / step))
        for j in range(k):
            t = j / k
            dense.append((ax + dx * t, ay + dy * t))
    return dense


def _smooth_closed_polyline(points, passes=3):
    if len(points) < 5:
        return points[:]
    pts = points[:]
    for _ in range(passes):
        out = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[(i - 1) % n]
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            out.append(((x0 + 2.0 * x1 + x2) * 0.25, (y0 + 2.0 * y1 + y2) * 0.25))
        pts = out
    return pts


def _project_to_driveable(points, driveable):
    h, w = driveable.shape
    out = []
    for x, y in points:
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < w and 0 <= iy < h and driveable[iy, ix]:
            out.append((float(ix), float(iy)))
            continue
        best = None
        best_d2 = 1e18
        R = 24
        for ry in range(max(0, iy - R), min(h, iy + R + 1)):
            for rx in range(max(0, ix - R), min(w, ix + R + 1)):
                if driveable[ry, rx]:
                    d2 = (rx - ix) ** 2 + (ry - iy) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best = (rx, ry)
        if best is not None:
            out.append((float(best[0]), float(best[1])))
        else:
            out.append((float(ix), float(iy)))
    return out


def _compute_curvature_and_speed(points, a_lat_max=180.0, vmin=40.0, vmax=360.0):
    n = len(points)
    if n < 5:
        return [
            {
                "x": p[0], "y": p[1], "heading": 0.0,
                "kappa": 0.0, "v_target": 120.0,
                "drift_zone": False, "drift_intensity": 0.0,
            }
            for p in points
        ]

    traj = []
    for i in range(n):
        x_prev, y_prev = points[(i - 1) % n]
        x, y = points[i]
        x_next, y_next = points[(i + 1) % n]

        tx = x_next - x_prev
        ty = y_next - y_prev
        heading = math.atan2(ty, tx)

        a = math.hypot(x - x_prev, y - y_prev)
        b = math.hypot(x_next - x, y_next - y)
        c = math.hypot(x_next - x_prev, y_next - y_prev)
        if a < 1e-6 or b < 1e-6 or c < 1e-6:
            kappa = 0.0
        else:
            area2 = abs((x - x_prev) * (y_next - y_prev) - (y - y_prev) * (x_next - x_prev))
            kappa = area2 / (a * b * c + 1e-9)

        v_target = math.sqrt(a_lat_max / max(kappa, 1e-5))
        v_target = max(vmin, min(vmax, v_target))

        drift_zone = kappa > 0.012
        drift_intensity = min(1.0, kappa * 80.0) if drift_zone else 0.0

        traj.append({
            "x": x, "y": y, "heading": heading,
            "kappa": kappa, "v_target": v_target,
            "drift_zone": drift_zone, "drift_intensity": drift_intensity,
        })
    return traj


def discover_track(
    map_path,
    start_pos=(220, 1700),
    start_angle=90,
    sample_rate=8,
    max_iterations=10000,
):
    meta = _load_map_meta_for_map(map_path)
    driveable = _build_driveable_mask(map_path, meta)

    cps = _ordered_checkpoint_centers(meta)
    if len(cps) < 3:
        r = 220.0
        pts = [
            (start_pos[0] + math.cos(i / 36.0 * 2 * math.pi) * r,
             start_pos[1] + math.sin(i / 36.0 * 2 * math.pi) * r)
            for i in range(36)
        ]
    else:
        pts = cps

    pts = _densify_closed_polyline(pts, step=20.0)
    pts = _project_to_driveable(pts, driveable)
    pts = _smooth_closed_polyline(pts, passes=4)
    trajectory = _compute_curvature_and_speed(pts)

    p = normalize_asset_path(map_path)
    map_num = 1
    try:
        parent_name = p.parent.name
        if parent_name.startswith("map"):
            map_num = int(parent_name.replace("map", ""))
    except Exception:
        pass

    return {
        "polyline": [(pt["x"], pt["y"]) for pt in trajectory],
        "trajectory": trajectory,
        "map_id": meta.get("map_name", f"map{map_num}"),
        "map_num": map_num,
    }


def discover_track_async(
    map_path,
    start_pos=(220, 1700),
    start_angle=90,
    sample_rate=8,
    max_iterations=10000,
):
    return _executor.submit(
        discover_track, map_path, start_pos, start_angle, sample_rate, max_iterations,
    )