import math
from typing import Dict, Tuple, List, Optional

try:
    import pygame_ce as pygame  # type: ignore
except Exception:  # pragma: no cover
    import pygame  # type: ignore

import const
from ui import draw_car


class WorldRenderer:
    """
    Renders the track, cars, and drift marks. Keeps internal state for tire marks
    and remote players' previous drift points.
    """

    def __init__(self, track_image: pygame.Surface, flags: int) -> None:
        self.track_image = track_image
        self.flags = flags
        self.tire_mark = pygame.Surface((track_image.get_width(), track_image.get_height()), pygame.SRCALPHA)
        self.tire_mark.fill((255, 255, 255, 0))
        self._drift_points_old_remotes: Dict[str, Tuple[Tuple[int, int], Tuple[int, int]]] = {}
        self._last_world_size: Optional[Tuple[int, int]] = (track_image.get_width(), track_image.get_height())

    def _ensure_tire_mark_size(self, world_size: Tuple[int, int]) -> bool:
        resized = False
        if (self.tire_mark.get_width(), self.tire_mark.get_height()) != world_size:
            self.tire_mark = pygame.Surface(world_size, pygame.SRCALPHA)
            self.tire_mark.fill((255, 255, 255, 0))
            resized = True
        self._last_world_size = world_size
        return resized

    def _draw_track(self, world_surf: pygame.Surface, cam, stage: str) -> None:
        if stage != "playing":
            world_surf.fill(const.GREY_20)
            return
        # Draw only the visible track region into the world surface
        top_left = (cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom,
                    cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom)
        camera_rect = pygame.Rect(top_left[0], top_left[1], const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
        visible = self.track_image.subsurface(camera_rect)
        world_surf.blit(visible, top_left)

    def _update_tire_marks(self, my_car, ai_cars: List, remotes: Dict[str, Dict], stage: str) -> None:
        # Local car drift marks
        if my_car.drift_ratio > 0.5 and my_car.drift_points_old:
            pygame.draw.line(self.tire_mark, const.TIRE_MARK_SMOKE, my_car.drift_points[0], my_car.drift_points_old[0], 3)
            pygame.draw.line(self.tire_mark, const.TIRE_MARK_SMOKE, my_car.drift_points[1], my_car.drift_points_old[1], 3)
        # AIs
        for ai_car in ai_cars:
            if ai_car.drift_ratio > 0.5 and ai_car.drift_points_old:
                pygame.draw.line(self.tire_mark, const.TIRE_MARK_SMOKE, ai_car.drift_points[0], ai_car.drift_points_old[0], 3)
                pygame.draw.line(self.tire_mark, const.TIRE_MARK_SMOKE, ai_car.drift_points[1], ai_car.drift_points_old[1], 3)
        # Remote players only when playing
        if stage == "playing":
            for pid, d in remotes.items():
                # draw_car returns rear tire points as (p2, p3)
                # Drift point accumulation happens after car drawing below to avoid duplication.
                pass

    def _blit_visible_tire_marks(self, world_surf: pygame.Surface, cam) -> None:
        # Fade accumulated marks from smoke color towards ground
        self.tire_mark.fill(const.TIRE_MARK_GROUND, special_flags=pygame.BLEND_RGBA_MULT)
        top_left = (cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom,
                    cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom)
        camera_rect = pygame.Rect(top_left[0], top_left[1], const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
        visible = self.tire_mark.subsurface(camera_rect)
        world_surf.blit(visible, top_left)

    def render_world(self,
                     cam,
                     stage: str,
                     my_car,
                     ai_cars: List,
                     remotes: Dict[str, Dict],
                     lights_on: bool,
                     car_sprites_list: List[List[pygame.Surface]],
                     draw_remotes: bool = True,
                     ) -> Tuple[pygame.Surface, bool]:
        """Render track, cars, and drift marks into a world surface.

        Returns (world_surface, resized_flag) where resized_flag is True if
        the internal tire mark surface resized this frame.
        """
        # Determine world surface size
        if stage != "playing":
            world_size = (const.WINDOW_WIDTH, const.WINDOW_HEIGHT)
        else:
            world_size = (self.track_image.get_width(), self.track_image.get_height())

        world_surf = pygame.Surface(world_size, self.flags)
        resized = self._ensure_tire_mark_size(world_size)

        # 1) Track
        self._draw_track(world_surf, cam, stage)

        # 2) Cars (AIs first)
        for ai_car in ai_cars:
            draw_car(world_surf, ai_car.x, ai_car.y, ai_car.angle, ai_car.name,
                     color_body=const.COLOR_BODY_DEFAULT,
                     car_sprites_list=car_sprites_list,
                     lights_on=lights_on)

        # 3) Tire marks accumulation for local and AIs
        self._update_tire_marks(my_car, ai_cars, remotes, stage)

        # 4) Blit visible tire marks segment
        self._blit_visible_tire_marks(world_surf, cam)

        # 5) Draw my car on top
        draw_car(world_surf, my_car.x, my_car.y, my_car.angle, my_car.name,
                 color_body=const.COLOR_MY_CAR,
                 car_sprites_list=car_sprites_list,
                 lights_on=lights_on)

        # 6) Remotes (draw + drift marks accumulation)
        if stage == "playing" and draw_remotes:
            for pid, d in remotes.items():
                drift_pts = draw_car(world_surf, d["x"], d["y"], d["a"], d.get("name", f"Player{pid}"),
                                     color_body=const.COLOR_BODY_REMOTE,
                                     car_sprites_list=car_sprites_list,
                                     lights_on=lights_on)
                if d.get("drift_ratio", 0.0) > 0.8 and pid in self._drift_points_old_remotes and drift_pts is not None:
                    old_pts = self._drift_points_old_remotes[pid]
                    pygame.draw.line(self.tire_mark, const.TIRE_MARK_SMOKE, drift_pts[0], old_pts[0], 3)
                    pygame.draw.line(self.tire_mark, const.TIRE_MARK_SMOKE, drift_pts[1], old_pts[1], 3)
                self._drift_points_old_remotes[pid] = drift_pts

        return world_surf, resized
