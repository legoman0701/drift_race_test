import pygame, math, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, Future
from PIL import Image

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from drift.config import const
from drift.tools.paths import normalize_asset_path, get_track_base_image_path, asset_path

# Background thread pool for non-blocking track discovery
_executor = ThreadPoolExecutor(max_workers=1)


def get_pathfinder_image_path(map_key):
    """Prefer map tracing image for path discovery, fallback to base image."""
    tr_path = asset_path("track", map_key, "main_tr.png")
    if tr_path.exists():
        return tr_path
    return get_track_base_image_path(map_key)


def _resolve_discovery_image_path(map_path):
    """Resolve discovery input as either map key (mapN) or asset/file path."""
    text = str(map_path)
    if text.lower().startswith("map") and "/" not in text and "\\" not in text:
        return get_pathfinder_image_path(text)
    return normalize_asset_path(map_path)


def _resolve_start_from_map_meta(map_path, fallback_pos=(220, 1700), fallback_angle=90):
    """Resolve discovery start from map_meta.json (average start x/y/a)."""
    meta_path = None
    text = str(map_path)

    if text.lower().startswith("map") and "/" not in text and "\\" not in text:
        meta_path = asset_path("track", text, "map_meta.json")
    else:
        image_path = Path(_resolve_discovery_image_path(map_path))
        meta_path = image_path.parent / "map_meta.json"

    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        starts = meta.get("start", []) or []
        if starts:
            avg_x = sum(s.get("x", 0.0) for s in starts) / len(starts)
            avg_y = sum(s.get("y", 0.0) for s in starts) / len(starts)
            avg_a = math.degrees(sum(s.get("a", 0.0) for s in starts) / len(starts))
            return (avg_x, avg_y), avg_a
    except Exception:
        pass

    return fallback_pos, fallback_angle


def _make_pil_raycast(px, width, height, length=800):
    """Return a raycast function backed by a PIL pixel array."""
    def color_dist(c1, c2):
        return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(c1[:3], c2[:3])))

    def raycast(pos, angle):
        x, y = pos[0], pos[1]
        ix, iy = int(x), int(y)
        if not (0 <= ix < width and 0 <= iy < height):
            return length
        base_color = px[ix, iy]
        for l in range(length):
            rx = int(x + math.cos(math.radians(angle)) * l)
            ry = int(y + math.sin(math.radians(angle)) * l)
            if 0 <= rx < width and 0 <= ry < height:
                if color_dist(px[rx, ry], base_color) > 100:
                    return l
        return length
    return raycast


def _make_pygame_raycast(surface, length=800):
    """Return a raycast function backed by a pygame Surface."""
    w, h = surface.get_width(), surface.get_height()
    def color_dist(c1, c2):
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(c1, c2)))
    def raycast(pos, angle):
        x, y = pos[0], pos[1]
        ix, iy = int(x), int(y)
        if not (0 <= ix < w and 0 <= iy < h):
            return length
        base_color = surface.get_at((ix, iy))
        for l in range(length):
            rx = int(x + math.cos(math.radians(angle)) * l)
            ry = int(y + math.sin(math.radians(angle)) * l)
            if 0 <= rx < w and 0 <= ry < h:
                if color_dist(surface.get_at((rx, ry)), base_color) > 100:
                    return l
        return length
    return raycast


def _sanitize_start_pos(start_pos, width, height):
    """Clamp discovery start position inside image bounds."""
    try:
        x = float(start_pos[0])
        y = float(start_pos[1])
    except Exception:
        return (max(0.0, (width - 1) * 0.5), max(0.0, (height - 1) * 0.5))

    x = min(max(0.0, x), max(0.0, width - 1))
    y = min(max(0.0, y), max(0.0, height - 1))
    return (x, y)


def _discovery_steps(raycast_fn, start_pos, start_angle, sample_rate, max_iterations=10000, width=None, height=None):
    """Generator: advance the track-following probe one step per iteration.

    Yields a state dict each step:
        pos         – (x, y) current probe position
        angle       – current heading in degrees
        left_angle  – angle of the left probe ray
        right_angle – angle of the right probe ray
        left_dist   – distance to left wall
        right_dist  – distance to right wall
        track_width – sum of left + right cross-track distances
        positions   – sampled polygon points so far
        done        – True when the loop has closed back to start
    """
    fx, fy = float(start_pos[0]), float(start_pos[1])
    angle = float(start_angle)
    positions = []

    def _is_in_bounds(x, y):
        if width is None or height is None:
            return True
        return 0 <= x < width and 0 <= y < height

    def _clamp_to_bounds(x, y):
        if width is None or height is None:
            return x, y
        return (
            min(max(0.0, x), max(0.0, width - 1)),
            min(max(0.0, y), max(0.0, height - 1)),
        )

    for iteration in range(max_iterations):
        left_angle  = angle - 70
        right_angle = angle + 70
        left_dist   = raycast_fn((fx, fy), left_angle)
        right_dist  = raycast_fn((fx, fy), right_angle)
        left_width  = raycast_fn((fx, fy), angle - 90)
        right_width = raycast_fn((fx, fy), angle + 90)

        angle += max(-5, min(5, (right_dist - left_dist) * 0.1))

        fx += math.cos(math.radians(angle)) * 4
        fy += math.sin(math.radians(angle)) * 4

        out_of_bounds = not _is_in_bounds(fx, fy)
        if out_of_bounds:
            fx, fy = _clamp_to_bounds(fx, fy)

        if iteration % sample_rate == 0 or out_of_bounds:
            positions.append((int(fx), int(fy), left_width + right_width))

        done_by_loop = (
            len(positions) > 50
            and math.hypot(fx - start_pos[0], fy - start_pos[1]) < 50
        )
        done = done_by_loop or out_of_bounds

        yield {
            "pos":         (fx, fy),
            "angle":       angle,
            "left_angle":  left_angle,
            "right_angle": right_angle,
            "left_dist":   left_dist,
            "right_dist":  right_dist,
            "track_width": left_width + right_width,
            "positions":   positions,
            "done":        done,
            "out_of_bounds": out_of_bounds,
        }

        if done:
            break


def discover_track(map_path, start_pos=None, start_angle=None, sample_rate=8, max_iterations=10000):
    """Discover track outline by following track edges using PIL (no pygame).

    Returns:
        List of (x, y, width) tuples representing the track path.
    """
    pil_img = Image.open(_resolve_discovery_image_path(map_path)).convert("RGBA")
    width, height = pil_img.size
    raycast = _make_pil_raycast(pil_img.load(), width, height)
    if start_pos is None or start_angle is None:
        meta_pos, meta_angle = _resolve_start_from_map_meta(map_path)
        if start_pos is None:
            start_pos = meta_pos
        if start_angle is None:
            start_angle = meta_angle
    safe_start_pos = _sanitize_start_pos(start_pos, width, height)

    positions = []
    for state in _discovery_steps(raycast, safe_start_pos, start_angle, sample_rate, max_iterations, width=width, height=height):
        positions = state["positions"]
    return positions


def discover_track_visual(map_path, start_pos=None, start_angle=None, sample_rate=8, max_iterations=10000):
    """Discover track with a live visual display. Returns the polygon when done."""
    bg_image = pygame.image.load(_resolve_discovery_image_path(map_path))
    image_surface = pygame.Surface((bg_image.get_width(), bg_image.get_height()))
    tmp_surf = pygame.Surface((bg_image.get_width(), bg_image.get_height()), pygame.SRCALPHA)

    pygame.init()
    screen = pygame.display.set_mode((bg_image.get_width() // 2, bg_image.get_height() // 2))
    pygame.display.set_caption("Track Discovery")
    image_surface.blit(bg_image, (0, 0))

    raycast = _make_pygame_raycast(image_surface)
    if start_pos is None or start_angle is None:
        meta_pos, meta_angle = _resolve_start_from_map_meta(map_path)
        if start_pos is None:
            start_pos = meta_pos
        if start_angle is None:
            start_angle = meta_angle
    safe_start_pos = _sanitize_start_pos(start_pos, bg_image.get_width(), bg_image.get_height())
    discovery = _discovery_steps(
        raycast,
        safe_start_pos,
        start_angle,
        sample_rate,
        max_iterations,
        width=bg_image.get_width(),
        height=bg_image.get_height(),
    )

    def draw_finder(surface, pos, angle):
        x, y = pos
        size = 30
        points = [
            (x + math.cos(math.radians(angle))       * size,       y + math.sin(math.radians(angle))       * size),
            (x + math.cos(math.radians(angle + 120)) * size * 0.6, y + math.sin(math.radians(angle + 120)) * size * 0.6),
            (x + math.cos(math.radians(angle - 120)) * size * 0.6, y + math.sin(math.radians(angle - 120)) * size * 0.6),
        ]
        pygame.draw.polygon(surface, (255, 0, 0), points)

    def draw_ray(surface, pos, angle, length, color):
        end = (
            pos[0] + math.cos(math.radians(angle)) * length,
            pos[1] + math.sin(math.radians(angle)) * length,
        )
        pygame.draw.line(surface, color, pos, end, 2)

    running = True
    positions = []

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                break

        if not running:
            break

        try:
            state = next(discovery)
        except StopIteration:
            break

        pos       = state["pos"]
        angle     = state["angle"]
        positions = state["positions"]

        screen.blit(pygame.transform.scale_by(image_surface, 0.5), (0, 0))
        tmp_surf.fill((0, 0, 0, 0))

        draw_ray(tmp_surf, pos, state["left_angle"],  state["left_dist"],  (0, 255, 0))
        draw_ray(tmp_surf, pos, state["right_angle"], state["right_dist"], (0, 255, 0))
        draw_ray(tmp_surf, pos, angle-90, state["track_width"]/2, (0, 255, 0))
        draw_ray(tmp_surf, pos, angle+90, state["track_width"]/2, (0, 255, 0))
        draw_finder(tmp_surf, pos, angle)

        if len(positions) >= 2:
            line_color = (255, 0, 0) if state["done"] else (0, 0, 255)
            for i in range(len(positions) - 1):
                ax, ay, aw = positions[i]
                bx, by, bw = positions[i + 1]
                half = (aw + bw) / 4  # half-width of the segment
                dx, dy = bx - ax, by - ay
                seg_len = math.hypot(dx, dy)
                if seg_len < 1e-4:
                    continue
                # Perpendicular unit vector
                px_u, py_u = -dy / seg_len * half, dx / seg_len * half
                quad = [
                    (ax + px_u, ay + py_u),
                    (ax - px_u, ay - py_u),
                    (bx - px_u, by - py_u),
                    (bx + px_u, by + py_u),
                ]
                pygame.draw.polygon(tmp_surf, line_color, quad)

        screen.blit(pygame.transform.scale_by(tmp_surf, 0.5), (0, 0))
        pygame.display.flip()
        #pygame.time.wait(500)
        if state["done"]:
            print("Loop completed — stopping discovery.")
            pygame.time.wait(500)
            break

    pygame.quit()
    return positions


def discover_track_async(map_path, start_pos=(220, 1700), start_angle=90, sample_rate=8, max_iterations=10000):
    """Start track discovery in a background thread. Returns a Future.
    
    Poll with future.done(); retrieve result with future.result().
    """
    return _executor.submit(discover_track, map_path, start_pos, start_angle, sample_rate, max_iterations)


if __name__ == "__main__":
    polygon = discover_track_visual(f"map{const.MAP_NUM}")
    print(f"Discovered track polygon with {len(polygon)} points")
