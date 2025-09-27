import pygame, math

class Spray:
    def __init__(self, width, height, color=(255, 255, 200), ambient=(0,0,0)):
        self.width = width
        self.height = height
        self.color = color
        self.surface = pygame.Surface((width, height), pygame.SRCALPHA)  # Surface with transparency

    def add_cone(self, x, y, angle, length, fov=35, steps=15):
        """Add a cone-shaped spray effect to simulate headlights."""
        snapped_angle = round(angle / (math.pi / 16)) * (math.pi / 16)
        cx, cy = x, y
        L = length
        half_fov = math.radians(fov / 2)
        a1 = snapped_angle - half_fov - 0.02
        a2 = snapped_angle + half_fov + 0.02
        for i in range(steps, 0, -1):
            t = i / steps # 0 -> 1
            val = t # 0 -> 1
            val2 = 0.5 + t/2 # 0.5 -> 1
            Lt = L * t # 0 -> L
            p0 = (cx, cy)
            p1 = (cx + math.cos(a1) * Lt, cy + math.sin(a1) * Lt)
            p2 = (cx + math.cos(a2) * Lt, cy + math.sin(a2) * Lt)
            pygame.draw.polygon(self.surface, 
                                (int(self.color[0] * val2), int(self.color[1] * val2), int(self.color[2] * val2), 50), 
                                (p0, p1, p2))

    def render(self):
        """Render the spray effect onto the screen."""
        return self.surface
