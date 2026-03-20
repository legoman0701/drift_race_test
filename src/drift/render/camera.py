import pygame

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

class Camera:
    def __init__(self, width, height, zoom=1.0):
        # screen/viewport output size in pixels that the camera should render to 
        self.width = width
        self.height = height
        # zoom coefficient (= 1 : no zoom, > 1 : zooms in, < 1 : zooms out)
        self.zoom = zoom
        # camera center in world coordinates
        self.x = width // 2
        self.y = height // 2
        self.offset = [0, 0]  # additional pan offset
        # smoothed velocity used to give the camera some intertial lead according to the target
        self.cam_vec_x = 0.0
        self.cam_vec_y = 0.0

    def update(self, target, world_size):
        # exponential smoothing: each frame the smoothed vector keeps 90% of the old value and adds 10% vel/4
        self.cam_vec_x = (target.vx / 4) * 0.1 + self.cam_vec_x * 0.9
        self.cam_vec_y = (target.vy / 4) * 0.1 + self.cam_vec_y * 0.9
        self.x = clamp(
            target.x + self.offset[0], # target’s position + pan offset
            self.width / 2 / self.zoom,
            world_size[0] - self.width / 2 / self.zoom,
        ) + self.cam_vec_x # add velocity lead
        self.y = clamp(
            target.y + self.offset[1],
            self.height / 2 / self.zoom,
            world_size[1] - self.height / 2 / self.zoom,
        ) + self.cam_vec_y

    def apply(self, world_surf):
        # actual screen size -> eg: if zoom=2, only the half of world's width is needed (bc we'll scale it up 2x later)
        view_w = int(self.width / self.zoom)
        view_h = int(self.height / self.zoom)
        # top left of the view rect to center on (x,y)
        left = int(self.x - view_w // 2)
        top = int(self.y - view_h // 2)
        # clamp the rect so it stays fully inside the world surf
        left = max(0, min(world_surf.get_width()-view_w, left))
        top = max(0, min(world_surf.get_height()-view_h, top))
        view_rect = pygame.Rect(left, top, view_w, view_h)
        view = world_surf.subsurface(view_rect) # subsurface of the world (visible slice)
        return pygame.transform.scale(view, (self.width, self.height))

    def apply_no_scale(self, world_surf):
        """Extract the visible view rect without CPU scaling (for GPU upscale)."""
        view_w = int(self.width / self.zoom)
        view_h = int(self.height / self.zoom)
        left = int(self.x - view_w // 2)
        top = int(self.y - view_h // 2)
        left = max(0, min(world_surf.get_width() - view_w, left))
        top = max(0, min(world_surf.get_height() - view_h, top))
        view_rect = pygame.Rect(left, top, view_w, view_h)
        return world_surf.subsurface(view_rect)
    