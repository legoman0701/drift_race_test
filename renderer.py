# global
from typing import Dict, Tuple, List, Optional
try: import pygame_ce as pygame  # type: ignore
except Exception: import pygame  # type: ignore
# local
import const
from ui import draw_car
from map_chunks import ChunkedMap, TireMarkGrid


class WorldRenderer:
    """
    Renders the track, cars, and tire marks.
    - Classic mode: single large track image (menus + fallback).
    - Chunk mode: when playing, we draw only the visible tiles (viewport-sized surface).
    """

    def __init__(self, track_image: pygame.Surface, flags: int, chunked_map: Optional[ChunkedMap] = None) -> None:
        self.track_image = track_image
        self.flags = flags
        self.chunked_map = chunked_map

        # classic tire mark acc (single surface sized to the whole map)
        self.tire_mark = pygame.Surface((track_image.get_width(), track_image.get_height()), pygame.SRCALPHA)
        self.tire_mark.fill((255, 255, 255, 0))
        
        # chuncked tire mark grid
        self.tire_mark_grid = TireMarkGrid(chunked_map.tile_size) if chunked_map else None

        self._drift_points_old_remotes: Dict[str, Tuple[Tuple[int, int], Tuple[int, int]]] = {}
        self._last_world_size: Optional[Tuple[int, int]] = (track_image.get_width(), track_image.get_height())

    # ---------- Classic helpers (single image) ----------
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

    # ---------- Chunked helpers (viewport-sized) ----------
    def _draw_track_chunked(self, viewport_surf: pygame.Surface, cam) -> pygame.Rect:
        top_left = (cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom,
                    cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom)
        camera_rect = pygame.Rect(top_left[0], top_left[1],
                                  const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
        self.chunked_map.render_to(viewport_surf, camera_rect)
        return camera_rect

    def _update_tire_marks_chunked(self, my_car, ai_cars: List, remotes: Dict[str, Dict]) -> None:
        self.tire_mark_grid.fade(const.TIRE_MARK_GROUND) # Fade a little each frame

        def add_two_lines(p_cur, p_old, ratio: float):
            if ratio > 0.5 and p_old:
                self.tire_mark_grid.draw_line_world(p_cur[0], p_old[0], const.TIRE_MARK_SMOKE, 3, self.chunked_map.tile_size)
                self.tire_mark_grid.draw_line_world(p_cur[1], p_old[1], const.TIRE_MARK_SMOKE, 3, self.chunked_map.tile_size)

        add_two_lines(my_car.drift_points, my_car.drift_points_old, my_car.drift_ratio)
        for ai_car in ai_cars:
            add_two_lines(ai_car.drift_points, ai_car.drift_points_old, ai_car.drift_ratio)

    def _blit_tire_marks_chunked(self, viewport_surf: pygame.Surface, camera_rect: pygame.Rect) -> None:
        self.tire_mark_grid.blit_visible(viewport_surf, camera_rect)

    # ---------- Public API ----------
    def get_world_size(self, stage: str) -> Tuple[int, int]:
        """
        Size used by physics/camera clamping. In chunked mode we expose a huge world
        so the camera and cars never clamp on artificial borders.
        """
        if stage != "playing":
            return (const.WINDOW_WIDTH, const.WINDOW_HEIGHT)
        if self.chunked_map:
            BIG = 10**9
            return (BIG, BIG)
        return (self.track_image.get_width(), self.track_image.get_height())

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
        """
        Render track, cars, and marks.

        Returns (surface, resized_flag, is_viewport):
        - is_viewport == False : classic path (world-sized surface, later cropped by cam.apply).
        - is_viewport == True  : chunked path (already a viewport-sized surface to blit/scale).
        """

        # -------- Chunked path --------
        if stage == "playing" and self.chunked_map is not None:
            # Viewport-sized canvas
            vw, vh = int(const.WINDOW_WIDTH / cam.zoom), int(const.WINDOW_HEIGHT / cam.zoom)
            world_surf = pygame.Surface((vw, vh), self.flags)

            # Track
            camera_rect = self._draw_track_chunked(world_surf, cam)

            # Tire marks accumulation (local + AIs)
            self._update_tire_marks_chunked(my_car, ai_cars, remotes)
            self._blit_tire_marks_chunked(world_surf, camera_rect)

            # Cars (AIs first)
            offx, offy = camera_rect.left, camera_rect.top
            for ai_car in ai_cars:
                draw_car(world_surf, ai_car.x - offx, ai_car.y - offy, ai_car.angle, ai_car.name,
                         color_body=const.COLOR_BODY_DEFAULT,
                         car_sprites_list=car_sprites_list,
                         lights_on=lights_on)

            # Player
            draw_car(world_surf, my_car.x - offx, my_car.y - offy, my_car.angle, my_car.name,
                     color_body=const.COLOR_MY_CAR,
                     car_sprites_list=car_sprites_list,
                     lights_on=lights_on)

            # Remotes (draw + their tire marks)
            if draw_remotes:
                for pid, d in remotes.items():
                    drift_pts = draw_car(world_surf, d["x"] - offx, d["y"] - offy, d["a"], d.get("name", f"Player{pid}"),
                                         color_body=const.COLOR_BODY_REMOTE,
                                         car_sprites_list=car_sprites_list,
                                         lights_on=lights_on)
                    if d.get("drift_ratio", 0.0) > 0.8 and pid in self._drift_points_old_remotes and drift_pts is not None:
                        old_pts = self._drift_points_old_remotes[pid]
                        # convert local back to world for the tire grid
                        w0 = (drift_pts[0][0] + offx, drift_pts[0][1] + offy)
                        w1 = (drift_pts[1][0] + offx, drift_pts[1][1] + offy)
                        o0 = (old_pts[0][0], old_pts[0][1])
                        o1 = (old_pts[1][0], old_pts[1][1])
                        self.tire_mark_grid.draw_line_world(w0, o0, const.TIRE_MARK_SMOKE, 3, self.chunked_map.tile_size)
                        self.tire_mark_grid.draw_line_world(w1, o1, const.TIRE_MARK_SMOKE, 3, self.chunked_map.tile_size)
                    self._drift_points_old_remotes[pid] = (
                        (drift_pts[0][0] + offx, drift_pts[0][1] + offy),
                        (drift_pts[1][0] + offx, drift_pts[1][1] + offy),
                    ) if drift_pts else None

            # No classic resize event here
            resized = False
            return world_surf, resized, True
        
        # -------- Classic path --------
        if stage != "playing":
            world_size = (const.WINDOW_WIDTH, const.WINDOW_HEIGHT)
        else:
            world_size = (self.track_image.get_width(), self.track_image.get_height())

        world_surf = pygame.Surface(world_size, self.flags)
        resized = self._ensure_tire_mark_size(world_size)

        # 1) Track
        self._draw_track(world_surf, cam, stage)

        # 2) AIs
        for ai_car in ai_cars:
            draw_car(world_surf, ai_car.x, ai_car.y, ai_car.angle, ai_car.name,
                     color_body=const.COLOR_BODY_DEFAULT,
                     car_sprites_list=car_sprites_list,
                     lights_on=lights_on)

        # 3) Tire marks accumulation
        self._update_tire_marks(my_car, ai_cars, remotes, stage)

        # 4) Blit visible marks
        self._blit_visible_tire_marks(world_surf, cam)

        # 5) Player
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

        return world_surf, resized, False
