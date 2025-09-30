try: import pygame_ce as pygame # type: ignore
except Exception: import pygame

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

class Camera:
    def __init__(self, width, height, zoom=1.0):
        self.width = width # bottom right corner's x value of zoomed camera 
        self.height = height # bottom right corner's y value of zoomed camera
        self.zoom = zoom
        self.x = width // 2
        self.y = height // 2
        self.offset = [0, 0]  # additional pan offset

    def update(self, target, world_size):
        # Follow the target with any offset
        self.x = clamp(target.x + self.offset[0], self.width / 2 / self.zoom, world_size[0] - self.width / 2 / self.zoom)
        self.y = clamp(target.y + self.offset[1], self.height / 2 / self.zoom, world_size[1] - self.height / 2 / self.zoom)

    def apply(self, world_surf):
        view_w = int(self.width / self.zoom)
        view_h = int(self.height / self.zoom)
        left = int(self.x - view_w // 2)
        top = int(self.y - view_h // 2)
        # Clamp the view rect within the world surface
        left = max(0, min(world_surf.get_width()-view_w, left))
        top = max(0, min(world_surf.get_height()-view_h, top))
        view_rect = pygame.Rect(left, top, view_w, view_h)
        view = world_surf.subsurface(view_rect)
        return pygame.transform.scale(view, (self.width, self.height))