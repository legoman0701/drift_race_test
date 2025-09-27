import pygame

class Camera:
    def __init__(self, width, height, zoom=1.0):
        self.width = width
        self.height = height
        self.zoom = zoom
        self.x = width // 2
        self.y = height // 2
        self.offset = [0, 0]  # additional pan offset

    def update(self, target):
        # Follow the target with any offset
        self.x = target.x + self.offset[0]
        self.y = target.y + self.offset[1]

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