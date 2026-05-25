import random
import math
import pygame
from drift.core.car import _wall_pushout


class Penguin:
    def __init__(self, x: float, y: float, sprite: pygame.Surface = None):
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.speed = random.uniform(30.0, 70.0)  # pixels per second
        self.target = (self.x, self.y)
        self.change_target_timer = 0.0
        self.sprite = sprite
        self.radius = 12.0

    def _pick_target(self):
        # pick new target within a 200px radius
        angle = random.random() * math.tau
        r = random.uniform(50.0, 200.0)
        tx = self.x + math.cos(angle) * r
        ty = self.y + math.sin(angle) * r
        self.target = (tx, ty)
        self.change_target_timer = random.uniform(1.0, 4.0)

    def step(self, dt: float, collision_mesh=None, cars: list = None):
        # dt in seconds
        self.change_target_timer -= dt
        if self.change_target_timer <= 0.0:
            self._pick_target()

        tx, ty = self.target
        dx = tx - self.x
        dy = ty - self.y
        dist = math.hypot(dx, dy)
        if dist < 4.0:
            # reached target, pick another
            self._pick_target()
            return
        # move towards target
        nx = dx / dist
        ny = dy / dist
        move = min(self.speed * dt, dist)
        old_x, old_y = self.x, self.y
        self.x += nx * move
        self.y += ny * move
        # update velocity from positional change
        if dt > 0:
            self.vx = (self.x - old_x) / dt
            self.vy = (self.y - old_y) / dt

        # Simple map collision pushout
        try:
            if collision_mesh:
                polys = collision_mesh.query_point(self.x, self.y) if hasattr(collision_mesh, 'query_point') else collision_mesh
                for polygon in polys:
                    if len(polygon) < 3:
                        continue
                    push_x, push_y, depth = _wall_pushout(self.x, self.y, polygon)
                    if depth > 0:
                        # push penguin out of wall
                        nxp = push_x / (depth if depth != 0 else 1.0)
                        nyp = push_y / (depth if depth != 0 else 1.0)
                        self.x += push_x + nxp * 0.5
                        self.y += push_y + nyp * 0.5
                        # damp velocity along normal
                        vnorm = (self.vx * nxp + self.vy * nyp)
                        self.vx -= vnorm * nxp * 0.8
                        self.vy -= vnorm * nyp * 0.8
                        # if position changed, reflect in small velocity update
                        if dt > 0:
                            self.vx = (self.x - old_x) / dt
                            self.vy = (self.y - old_y) / dt
        except Exception:
            pass

        # Simple car collisions
        try:
            if cars:
                for car in cars:
                    cx, cy = getattr(car, 'x', None), getattr(car, 'y', None)
                    if cx is None or cy is None:
                        continue
                    dx = self.x - cx
                    dy = self.y - cy
                    d2 = dx * dx + dy * dy
                    car_r = 30.0
                    try:
                        specs = getattr(car, '_cached_specs_vals', None)
                        if specs:
                            car_r = max(8.0, max(specs.get('CAR_LEN', 38.0), specs.get('CAR_WID', 20.0)) * 0.6)
                    except Exception:
                        car_r = 30.0
                    min_dist = (self.radius + car_r)
                    if d2 < (min_dist * min_dist) and d2 > 1e-6:
                        d = math.sqrt(d2)
                        nxp = dx / d
                        nyp = dy / d
                        overlap = min_dist - d
                        # push penguin out
                        self.x += nxp * overlap * 1.0
                        self.y += nyp * overlap * 1.0
                        # transfer small impulse to car (nudge)
                        try:
                            push_impulse = 0.5
                            car.vx -= nxp * push_impulse
                            car.vy -= nyp * push_impulse
                        except Exception:
                            pass
                        # reduce penguin speed a bit
                        self.vx *= 0.6
                        self.vy *= 0.6
        except Exception:
            pass

    def draw(self, surf: pygame.Surface, offx: float = 0.0, offy: float = 0.0, scale: float = 1.0):
        px = int(round(self.x - offx))
        py = int(round(self.y - offy))
        moving_right = getattr(self, 'vx', 0.0) > 0.5
        if self.sprite:
            try:
                # scale sprite according to provided scale
                sw = max(1, int(self.sprite.get_width() * scale))
                sh = max(1, int(self.sprite.get_height() * scale))
                if sw != self.sprite.get_width() or sh != self.sprite.get_height():
                    img = pygame.transform.smoothscale(self.sprite, (sw, sh))
                else:
                    img = self.sprite
                # flip vertically when moving right per request
                if moving_right:
                    img = pygame.transform.flip(img, True, False)
                rect = img.get_rect(center=(px, py))
                surf.blit(img, rect)
                return
            except Exception:
                pass
        # basic fallback penguin: black body with white belly and small beak
        # body
        pygame.draw.circle(surf, (0, 0, 0), (px, py), int(10 * scale))
        # belly
        pygame.draw.circle(surf, (255, 255, 255), (px, py + int(2 * scale)), int(6 * scale))
        # beak (flip side if moving right)
        if moving_right:
            beak = [(px - int(8 * scale), py), (px - int(12 * scale), py + int(2 * scale)), (px - int(8 * scale), py + int(4 * scale))]
        else:
            beak = [(px + int(8 * scale), py), (px + int(12 * scale), py + int(2 * scale)), (px + int(8 * scale), py + int(4 * scale))]
        pygame.draw.polygon(surf, (255, 160, 60), beak)
