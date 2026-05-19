import pygame, math
from concurrent.futures import ThreadPoolExecutor, Future
from PIL import Image

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))

from drift.config import const
from drift.tools.paths import normalize_asset_path, get_track_base_image_path

# Background thread pool for non-blocking track discovery
_executor = ThreadPoolExecutor(max_workers=1)


def _make_pil_raycast(px, width, height, length=800):
    """Return a raycast function backed by a PIL pixel array."""
    def raycast(pos, angle):
        x, y = pos[0], pos[1]
        for l in range(length):
            rx = int(x + math.cos(math.radians(angle)) * l)
            ry = int(y + math.sin(math.radians(angle)) * l)
            if 0 <= rx < width and 0 <= ry < height:
                if px[rx, ry][1] > 180:
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
        base_color = surface.get_at((int(x), int(y)))
        for l in range(length):
            rx = int(x + math.cos(math.radians(angle)) * l)
            ry = int(y + math.sin(math.radians(angle)) * l)
            if 0 <= rx < w and 0 <= ry < h:
                if color_dist(surface.get_at((rx, ry)), base_color) > 100:
                    return l
        return length
    return raycast


def _discovery_steps(raycast_fn, start_pos, start_angle, sample_rate, max_iterations=10000):
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

    for iteration in range(max_iterations):
        left_angle  = angle - 45
        right_angle = angle + 45
        left_dist   = raycast_fn((fx, fy), left_angle)
        right_dist  = raycast_fn((fx, fy), right_angle)
        left_width  = raycast_fn((fx, fy), angle - 90)
        right_width = raycast_fn((fx, fy), angle + 90)

        angle += max(-5, min(5, (right_dist - left_dist) * 0.1))

        fx += math.cos(math.radians(angle)) * 4
        fy += math.sin(math.radians(angle)) * 4

        if iteration % sample_rate == 0:
            positions.append((int(fx), int(fy), left_width + right_width))

        done = (
            len(positions) > 50
            and math.hypot(fx - start_pos[0], fy - start_pos[1]) < 50
        )

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
        }

        if done:
            break


def discover_track(map_path, start_pos=(220, 1700), start_angle=90, sample_rate=8, max_iterations=10000):
    """Discover track outline by following track edges using PIL (no pygame).

    Returns:
        List of (x, y, width) tuples representing the track path.
    """
    pil_img = Image.open(normalize_asset_path(map_path)).convert("RGBA")
    width, height = pil_img.size
    raycast = _make_pil_raycast(pil_img.load(), width, height)

    positions = []
    for state in _discovery_steps(raycast, start_pos, start_angle, sample_rate, max_iterations):
        positions = state["positions"]
    return positions


def discover_track_visual(map_path, start_pos=(220, 1700), start_angle=90, sample_rate=8, max_iterations=10000):
    """Discover track with a live visual display. Returns the polygon when done."""
    bg_image = pygame.image.load(normalize_asset_path(map_path))
    image_surface = pygame.Surface((bg_image.get_width(), bg_image.get_height()))
    tmp_surf = pygame.Surface((bg_image.get_width(), bg_image.get_height()), pygame.SRCALPHA)

    pygame.init()
    screen = pygame.display.set_mode((bg_image.get_width() // 2, bg_image.get_height() // 2))
    pygame.display.set_caption("Track Discovery")
    image_surface.blit(bg_image, (0, 0))

    raycast = _make_pygame_raycast(image_surface)
    discovery = _discovery_steps(raycast, start_pos, start_angle, sample_rate, max_iterations)

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
    polygon = discover_track_visual(get_track_base_image_path(f"map{const.MAP_NUM}"))
    print(f"Discovered track polygon with {len(polygon)} points")
