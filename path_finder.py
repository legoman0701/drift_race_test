import pygame, math
from PIL import Image


def discover_track(map_path, start_pos=(1000, 450), start_angle=0, sample_rate=8, max_iterations=10000):
    """
    Discover track outline by following the track edges using PIL (no pygame).
    Args:
        map_path: Path to the track image
        start_pos: Starting position (x, y)
        start_angle: Starting angle in degrees
        sample_rate: Sample position every N frames
        max_iterations: Maximum iterations before stopping
    Returns:
        List of (x, y) tuples representing the track polygon
    """
    pil_img = Image.open(map_path).convert("RGBA")
    width, height = pil_img.size
    px = pil_img.load()

    finder_pos = (float(start_pos[0]), float(start_pos[1]))
    finder_angle = float(start_angle)
    positions = []
    iterations = 0

    def raycast(pos, angle, length=800):
        x, y = pos
        for l in range(length):
            rx = int(x + math.cos(math.radians(angle)) * l)
            ry = int(y + math.sin(math.radians(angle)) * l)
            if 0 <= rx < width and 0 <= ry < height:
                color = px[rx, ry]
                # color can be (r,g,b) or (r,g,b,a)
                blue = color[2] if len(color) >= 3 else 0
                if blue > 70:  # same heuristic as before
                    return l
        return length

    while iterations < max_iterations:
        # Move finder forward and steer to keep track centered
        left_angle = finder_angle - 45
        right_angle = finder_angle + 45
        left_dist = raycast(finder_pos, left_angle)
        right_dist = raycast(finder_pos, right_angle)

        # Calculate steering
        center_offset = right_dist - left_dist
        steer = max(-5, min(5, center_offset * 0.1))
        finder_angle += steer

        # Move forward
        speed = 4
        finder_pos = (
            finder_pos[0] + math.cos(math.radians(finder_angle)) * speed,
            finder_pos[1] + math.sin(math.radians(finder_angle)) * speed
        )

        # Sample positions
        if iterations % sample_rate == 0:
            positions.append((int(finder_pos[0]), int(finder_pos[1])))

        # Check if we've completed a loop (back near start)
        if len(positions) > 50:
            start_x, start_y = start_pos
            curr_x, curr_y = finder_pos
            distance_to_start = math.hypot(curr_x - start_x, curr_y - start_y)
            if distance_to_start < 50:
                break

        iterations += 1

    return positions


def discover_track_visual(map_path, start_pos=(1000, 450), start_angle=0, sample_rate=8):
    """
    Discover track with visual display (original functionality).
    Returns the polygon when window is closed.
    """
    bg_image = pygame.image.load(map_path)
    image_surface = pygame.Surface((bg_image.get_width(), bg_image.get_height()))
    tmp_drawing_surf = pygame.Surface((bg_image.get_width(), bg_image.get_height()), pygame.SRCALPHA)

    pygame.init()
    screen = pygame.display.set_mode((bg_image.get_width()//2, bg_image.get_height()//2))
    pygame.display.set_caption("Track Discovery")

    image_surface.blit(bg_image, (0, 0))

    finder_pos = start_pos
    finder_angle = start_angle
    positions = []
    frame = 0

    def draw_finder(surface, pos, angle):
        x, y = pos
        size = 30
        points = [
            (x + math.cos(math.radians(angle)) * size, y + math.sin(math.radians(angle)) * size),
            (x + math.cos(math.radians(angle + 120)) * size * 0.6, y + math.sin(math.radians(angle + 120)) * size * 0.6),
            (x + math.cos(math.radians(angle - 120)) * size * 0.6, y + math.sin(math.radians(angle - 120)) * size * 0.6),
        ]
        pygame.draw.polygon(surface, (255, 0, 0), points)

    def raycast(surface, pos, angle, length=800):
        x, y = pos
        for l in range(length):
            rx = int(x + math.cos(math.radians(angle)) * l)
            ry = int(y + math.sin(math.radians(angle)) * l)
            if 0 <= rx < surface.get_width() and 0 <= ry < surface.get_height():
                color = surface.get_at((rx, ry))
                if color[2] > 70:
                    return l
        return length

    def draw_ray(surface, pos, angle, length, color):
        end = (
            pos[0] + math.cos(math.radians(angle)) * length,
            pos[1] + math.sin(math.radians(angle)) * length
        )
        pygame.draw.line(surface, color, pos, end, 2)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        screen.blit(pygame.transform.scale_by(image_surface, 0.5), (0, 0))

        left_angle = finder_angle - 45
        right_angle = finder_angle + 45
        left_dist = raycast(image_surface, finder_pos, left_angle)
        right_dist = raycast(image_surface, finder_pos, right_angle)

        center_offset = right_dist - left_dist
        steer = max(-5, min(5, center_offset * 0.1))
        finder_angle += steer

        speed = 4
        finder_pos = (
            finder_pos[0] + math.cos(math.radians(finder_angle)) * speed,
            finder_pos[1] + math.sin(math.radians(finder_angle)) * speed
        )

        tmp_drawing_surf.fill((0, 0, 0, 0))

        draw_ray(tmp_drawing_surf, finder_pos, left_angle, left_dist, (0, 255, 0))
        draw_ray(tmp_drawing_surf, finder_pos, right_angle, right_dist, (0, 255, 0))
        draw_finder(tmp_drawing_surf, finder_pos, finder_angle)

        frame += 1
        if frame % sample_rate == 0:
            positions.append((int(finder_pos[0]), int(finder_pos[1])))

        if len(positions) >= 3:
            pygame.draw.polygon(tmp_drawing_surf, (0, 0, 255), positions, 2)

        if len(positions) > 50:
            start_x, start_y = start_pos
            curr_x, curr_y = finder_pos
            distance_to_start = math.hypot(curr_x - start_x, curr_y - start_y)
            if distance_to_start < 50:
                print("Loop completed — stopping discovery.")
                pygame.draw.polygon(tmp_drawing_surf, (255, 0, 0), positions, 3)
                screen.blit(pygame.transform.scale_by(tmp_drawing_surf, 0.5), (0, 0))
                pygame.display.flip()
                pygame.time.wait(500)
                running = False

        screen.blit(pygame.transform.scale_by(tmp_drawing_surf, 0.5), (0, 0))
        pygame.display.flip()

    pygame.quit()
    return positions


if __name__ == "__main__":
    # Run visual version when called directly
    polygon = discover_track_visual("assets/Map/Map1.png")
    print(f"Discovered track polygon with {len(polygon)} points")
