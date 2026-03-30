# global
import pygame
import math
from typing import Dict, Tuple, List, Optional
# local
import drift.config.const as const
from drift.ui.ui import draw_car, draw_wheel_debug, draw_collision_debug
from drift.ui.draw_stage import get_palette_colors
from drift.render.map_chunks import ChunkedMap, TireMarkGrid


class WorldRenderer:
    """
    Renders the track, cars, and tire marks.
    - Classic mode: single large track image (menus + fallback).
    - Chunk mode: when playing, we draw only the visible tiles (viewport-sized surface).
    """

    def __init__(self, track_image: pygame.Surface, flags: int, chunked_map: Optional[ChunkedMap] = None, checkpoints: Optional[List[pygame.Rect]] = None) -> None:
        self.track_image = track_image
        self.flags = flags
        self.chunked_map = chunked_map
        self.checkpoints = checkpoints
        self.collision_mesh = []  # populated from app.py

        # classic tire mark acc (single surface sized to the whole map)
        self.tire_mark = pygame.Surface((track_image.get_width(), track_image.get_height()), pygame.SRCALPHA)
        self.tire_mark.fill((255, 255, 255, 0))
        
        # chuncked tire mark grid
        self.tire_mark_grid = TireMarkGrid(chunked_map.tile_size) if chunked_map else None

        self._drift_points_old_remotes: Dict[str, Tuple[Tuple[int, int], ...]] = {}
        self._last_world_size: Optional[Tuple[int, int]] = (track_image.get_width(), track_image.get_height())
        
        # Frame counter for fade optimization
        self._fade_frame_counter = 0

        # Cached reusable surfaces to avoid per-frame allocation
        self._viewport_surf: Optional[pygame.Surface] = None
        self._viewport_size: Tuple[int, int] = (0, 0)
        self._classic_surf: Optional[pygame.Surface] = None
        self._classic_size: Tuple[int, int] = (0, 0)

    def _get_viewport_surf(self, w: int, h: int) -> pygame.Surface:
        """Return a cached viewport surface, reallocating only on size change."""
        if self._viewport_surf is None or self._viewport_size != (w, h):
            self._viewport_surf = pygame.Surface((w, h), self.flags)
            self._viewport_size = (w, h)
        self._viewport_surf.fill(const.GREY_20)
        return self._viewport_surf

    def _get_classic_surf(self, w: int, h: int) -> pygame.Surface:
        """Return a cached classic world surface, reallocating only on size change."""
        if self._classic_surf is None or self._classic_size != (w, h):
            self._classic_surf = pygame.Surface((w, h), self.flags)
            self._classic_size = (w, h)
        return self._classic_surf

    def clear_tire_marks(self) -> None:
        """Clear all tire marks (both classic and chunked modes)."""
        # Clear classic tire mark surface
        self.tire_mark.fill((255, 255, 255, 0))
        # Clear chunked tire mark grid
        if self.tire_mark_grid:
            self.tire_mark_grid._marks.clear()
        # Clear remote drift points tracking
        self._drift_points_old_remotes.clear()
    
    def clear_chunk_cache(self) -> None:
        """Clear chunk cache to free memory."""
        if self.chunked_map:
            self.chunked_map._cache.clear()

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
        if not stage.startswith("mode"):
            world_surf.fill(const.GREY_20)
            return
        # Draw only the visible track region into the world surface
        top_left = (cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom,
                    cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom)
        # Use an integer rect and clamp it to the track_image bounds before calling subsurface.
        camera_rect = pygame.Rect(top_left[0], top_left[1], const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
        camera_int = pygame.Rect(int(camera_rect.left), int(camera_rect.top), int(camera_rect.width), int(camera_rect.height))
        surf_rect = self.track_image.get_rect()
        inter = camera_int.clip(surf_rect)
        if inter.width > 0 and inter.height > 0:
            visible = self.track_image.subsurface(inter)
            # Blit at the intersection's topleft so the visible piece appears at the correct world location.
            world_surf.blit(visible, inter.topleft)

    def _update_tire_marks(self, my_car, ai_cars: List, remotes: Dict[str, Dict], stage: str) -> None:
        def draw_car_marks(car_obj) -> None:
            if not car_obj.drift_points_old or not getattr(car_obj, "has_grip", None):
                return
            for i, grip in enumerate(car_obj.has_grip):
                if i >= len(car_obj.drift_points) or i >= len(car_obj.drift_points_old):
                    continue
                # Validate points are proper tuples with 2 numeric values
                pt1 = car_obj.drift_points[i]
                pt2 = car_obj.drift_points_old[i]
                if (not isinstance(pt1, (tuple, list)) or len(pt1) != 2 or
                    not isinstance(pt2, (tuple, list)) or len(pt2) != 2):
                    continue
                # Skip if any element is None
                if pt1[0] is None or pt1[1] is None or pt2[0] is None or pt2[1] is None:
                    continue
                # Ensure values are finite numbers and within reasonable bounds
                try:
                    x1, y1 = float(pt1[0]), float(pt1[1])
                    x2, y2 = float(pt2[0]), float(pt2[1])
                    if not (math.isfinite(x1) and math.isfinite(y1) and 
                            math.isfinite(x2) and math.isfinite(y2)):
                        continue
                    # Clamp to reasonable bounds to avoid overflow
                    x1 = max(-1000000, min(1000000, x1))
                    y1 = max(-1000000, min(1000000, y1))
                    x2 = max(-1000000, min(1000000, x2))
                    y2 = max(-1000000, min(1000000, y2))
                    # Convert to plain Python int (not numpy.int64 or other types)
                    ix1, iy1 = int(round(x1)), int(round(y1))
                    ix2, iy2 = int(round(x2)), int(round(y2))
                except (ValueError, TypeError, OverflowError):
                    continue
                if float(grip) >= 0.3:
                    continue
                # Lower grip means stronger tire mark for that specific wheel.
                slip = max(0.0, min(1.0, 1.0 - float(grip)))
                alpha = int(60 + 180 * slip)
                smoke_color = (const.TIRE_MARK_SMOKE[0], const.TIRE_MARK_SMOKE[1], const.TIRE_MARK_SMOKE[2], alpha)
                try:
                    pygame.draw.line(self.tire_mark, smoke_color, (ix1, iy1), (ix2, iy2), 3)
                except (TypeError, ValueError, OverflowError) as e:
                    # Debug: print what caused the error
                    print(f"Draw error: pt1={pt1}, pt2={pt2}, converted=({ix1},{iy1}),({ix2},{iy2}), error={e}")
                    pass

        draw_car_marks(my_car)
        for ai_car in ai_cars:
            draw_car_marks(ai_car)
        # Remote players only when on game stage
        if stage.startswith("mode"):
            for pid, d in remotes.items():
                # draw_car returns rear tire points as (p2, p3)
                # Drift point accumulation happens after car drawing below to avoid duplication.
                pass

    def _blit_visible_tire_marks(self, world_surf: pygame.Surface, cam) -> None:
        # Fade accumulated marks from smoke color towards ground (faster fade for better performance)
        self.tire_mark.fill((200, 200, 200, 255), special_flags=pygame.BLEND_RGBA_MULT)
        top_left = (cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom,
                    cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom)
        camera_rect = pygame.Rect(top_left[0], top_left[1], const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
        camera_int = pygame.Rect(int(camera_rect.left), int(camera_rect.top), int(camera_rect.width), int(camera_rect.height))
        surf_rect = self.tire_mark.get_rect()
        inter = camera_int.clip(surf_rect)
        if inter.width > 0 and inter.height > 0:
            visible = self.tire_mark.subsurface(inter)
            world_surf.blit(visible, inter.topleft)

    # ---------- Chunked helpers (viewport-sized) ----------
    def _draw_track_chunked(self, viewport_surf: pygame.Surface, cam) -> pygame.Rect:
        top_left = (cam.x - (const.WINDOW_WIDTH / 2) / cam.zoom,
                    cam.y - (const.WINDOW_HEIGHT / 2) / cam.zoom)
        camera_rect = pygame.Rect(top_left[0], top_left[1],
                                  const.WINDOW_WIDTH / cam.zoom, const.WINDOW_HEIGHT / cam.zoom)
        self.chunked_map.render_to(viewport_surf, camera_rect)
        return camera_rect

    def _update_tire_marks_chunked(self, my_car, ai_cars: List, remotes: Dict[str, Dict], camera_rect: pygame.Rect) -> None:
        self._fade_frame_counter += 1
        if self._fade_frame_counter % 3 == 0:
            # Fade only the chunks that are actually visible
            self.tire_mark_grid.fade_visible(camera_rect, (185, 185, 185, 255))
        # Evict every chunk that is outside the visible tile range (no buffer margin)
        self.tire_mark_grid.remove_offscreen_chunks(camera_rect, margin=0)

        def add_per_wheel_lines(car_obj) -> None:
            if not car_obj.drift_points_old or not getattr(car_obj, "has_grip", None):
                return
            for i, grip in enumerate(car_obj.has_grip):
                if i >= len(car_obj.drift_points) or i >= len(car_obj.drift_points_old):
                    continue
                # Validate points are proper tuples with 2 numeric values
                pt1 = car_obj.drift_points[i]
                pt2 = car_obj.drift_points_old[i]
                if (not isinstance(pt1, (tuple, list)) or len(pt1) != 2 or
                    not isinstance(pt2, (tuple, list)) or len(pt2) != 2):
                    continue
                # Skip if any element is None
                if pt1[0] is None or pt1[1] is None or pt2[0] is None or pt2[1] is None:
                    continue
                # Ensure values are finite numbers and within reasonable bounds
                try:
                    x1, y1 = float(pt1[0]), float(pt1[1])
                    x2, y2 = float(pt2[0]), float(pt2[1])
                    if not (math.isfinite(x1) and math.isfinite(y1) and 
                            math.isfinite(x2) and math.isfinite(y2)):
                        continue
                    # Clamp to reasonable bounds to avoid overflow
                    x1 = max(-1000000, min(1000000, x1))
                    y1 = max(-1000000, min(1000000, y1))
                    x2 = max(-1000000, min(1000000, x2))
                    y2 = max(-1000000, min(1000000, y2))
                    # Convert to plain Python int (not numpy.int64 or other types)
                    ix1, iy1 = int(round(x1)), int(round(y1))
                    ix2, iy2 = int(round(x2)), int(round(y2))
                except (ValueError, TypeError, OverflowError):
                    continue
                if float(grip) >= 0.3:
                    continue
                slip = max(0.0, min(1.0, 1.0 - float(grip)))
                alpha = int(60 + 180 * slip)
                smoke_color = (const.TIRE_MARK_SMOKE[0], const.TIRE_MARK_SMOKE[1], const.TIRE_MARK_SMOKE[2], alpha)
                try:
                    self.tire_mark_grid.draw_line_world((ix1, iy1), (ix2, iy2), smoke_color, 3, self.chunked_map.tile_size)
                except (TypeError, ValueError, OverflowError) as e:
                    # Debug: print what caused the error
                    print(f"Draw chunked error: pt1={pt1}, pt2={pt2}, converted=({ix1},{iy1}),({ix2},{iy2}), error={e}")
                    pass

        add_per_wheel_lines(my_car)
        for ai_car in ai_cars:
            add_per_wheel_lines(ai_car)

    def _blit_tire_marks_chunked(self, viewport_surf: pygame.Surface, camera_rect: pygame.Rect) -> None:
        self.tire_mark_grid.blit_visible(viewport_surf, camera_rect)

    # ---------- Public API ----------
    def get_world_size(self, stage: str) -> Tuple[int, int]:
        """
        Size used by physics/camera clamping.
        """
        if not stage.startswith("mode"):
            return (const.WINDOW_WIDTH, const.WINDOW_HEIGHT)
        if self.chunked_map and hasattr(self.chunked_map, "get_world_size"):
            return self.chunked_map.get_world_size()  # use finite dimensions of the chunked map
        else:
            return (self.track_image.get_width(), self.track_image.get_height())

    def render_world(self,
                     cam,
                     stage: str,
                     my_car,
                     ai_cars: List,
                     remotes: Dict[str, Dict],
                     lights_on: bool,
                     car_sprites_cache: Dict[str, List[List[pygame.Surface]]],
                     draw_remotes: bool = True,
                     ) -> Tuple[pygame.Surface, bool]:
        """
        Render track, cars, and marks.

        Returns (surface, resized_flag, is_viewport):
        - is_viewport == False : classic path (world-sized surface, later cropped by cam.apply).
        - is_viewport == True  : chunked path (already a viewport-sized surface to blit/scale).
        """

        # mode stages (draw chunk map)
        if stage.startswith("mode") and self.chunked_map is not None:
            # Viewport-sized canvas (reuse cached surface)
            vw, vh = int(const.WINDOW_WIDTH / cam.zoom), int(const.WINDOW_HEIGHT / cam.zoom)
            world_surf = self._get_viewport_surf(vw, vh)

            # Track
            camera_rect = self._draw_track_chunked(world_surf, cam)

            # Tire marks accumulation (local + AIs)
            self._update_tire_marks_chunked(my_car, ai_cars, remotes, camera_rect)
            self._blit_tire_marks_chunked(world_surf, camera_rect)

            # Cars (AIs first)
            offx, offy = camera_rect.left, camera_rect.top
            for ai_car in ai_cars:
                car_sprites = car_sprites_cache.get(ai_car.car_type, car_sprites_cache.get("ae86", []))
                draw_car(world_surf, ai_car.x - offx, ai_car.y - offy, ai_car.angle, ai_car.name,
                         color_body=const.COLOR_BODY_DEFAULT,
                         car_sprites_list=car_sprites,
                         lights_on=lights_on,
                         palette_colors=getattr(ai_car, 'palette_colors', None))

            # Player
            my_car_sprites = car_sprites_cache.get(my_car.car_type, car_sprites_cache.get("ae86", []))
            draw_car(world_surf, my_car.x - offx, my_car.y - offy, my_car.angle, my_car.name,
                     color_body=const.COLOR_MY_CAR,
                     car_sprites_list=my_car_sprites,
                     lights_on=lights_on,
                     palette_colors=get_palette_colors())
            # Per-wheel debug overlay for local car
            if const.DEBUG:
                # Draw debug overlays for AIs as well as the local player
                for ai_car in ai_cars:
                    draw_wheel_debug(world_surf, ai_car, offx, offy)
                    draw_collision_debug(world_surf, ai_car, self.collision_mesh, offx, offy)
                draw_wheel_debug(world_surf, my_car, offx, offy)
                draw_collision_debug(world_surf, my_car, self.collision_mesh, offx, offy)

            # Remotes (draw + their tire marks)
            if draw_remotes:
                for pid, d in remotes.items():
                    # Use remote player's car_type (fallback to ae86 if not available)
                    remote_car_sprites = car_sprites_cache.get(d.get("car_type", "ae86"), car_sprites_cache.get("ae86", []))
                    drift_pts = draw_car(world_surf, d["x"] - offx, d["y"] - offy, d["a"], d.get("name", f"Player{pid}"),
                                         color_body=const.COLOR_BODY_REMOTE,
                                         car_sprites_list=remote_car_sprites,
                                         lights_on=lights_on,
                                         palette_colors=d.get("palette"))
                    remote_in_view = camera_rect.collidepoint(d["x"], d["y"])
                    if remote_in_view and pid in self._drift_points_old_remotes and drift_pts is not None:
                        old_pts = self._drift_points_old_remotes[pid]
                        remote_grip = d.get("has_grip", (1.0, 1.0, 1.0, 1.0))
                        for i, grip in enumerate(remote_grip):
                            if i >= len(drift_pts) or i >= len(old_pts):
                                continue
                            if float(grip) >= 0.3:
                                continue
                            slip = max(0.0, min(1.0, 1.0 - float(grip)))
                            alpha = int(60 + 180 * slip)
                            smoke_color = (const.TIRE_MARK_SMOKE[0], const.TIRE_MARK_SMOKE[1], const.TIRE_MARK_SMOKE[2], alpha)
                            w_cur = (drift_pts[i][0] + offx, drift_pts[i][1] + offy)
                            w_old = old_pts[i]
                            self.tire_mark_grid.draw_line_world(w_cur, w_old, smoke_color, 3, self.chunked_map.tile_size)
                    self._drift_points_old_remotes[pid] = tuple(
                        (pt[0] + offx, pt[1] + offy) for pt in drift_pts
                    ) if drift_pts else ()

            # No classic resize event here
            resized = False
            return world_surf, resized, True
        
        # -------- Classic path --------
        if not stage.startswith("mode"):
            world_size = (const.WINDOW_WIDTH, const.WINDOW_HEIGHT)
        else:
            world_size = (self.track_image.get_width(), self.track_image.get_height())

        world_surf = self._get_classic_surf(*world_size)
        resized = self._ensure_tire_mark_size(world_size)

        # 1) Draw the background track image
        self._draw_track(world_surf, cam, stage)

        # 2) Tire Marks
        self._update_tire_marks(my_car, ai_cars, remotes, stage)
        self._blit_visible_tire_marks(world_surf, cam)

        # 3) Draw all local AI-controlled cars
        for ai_car in ai_cars:
            car_sprites = car_sprites_cache.get(ai_car.car_type, car_sprites_cache.get("ae86", []))
            draw_car(world_surf, ai_car.x, ai_car.y, ai_car.angle, ai_car.name,
                     color_body=const.COLOR_BODY_DEFAULT,
                     car_sprites_list=car_sprites,
                     lights_on=lights_on,
                     palette_colors=getattr(ai_car, 'palette_colors', None))

        # 4) Player Car
        my_car_sprites = car_sprites_cache.get(my_car.car_type, car_sprites_cache.get("ae86", []))
        draw_car(world_surf, my_car.x, my_car.y, my_car.angle, my_car.name,
                 color_body=const.COLOR_MY_CAR,
                 car_sprites_list=my_car_sprites,
                 lights_on=lights_on,
                 palette_colors=get_palette_colors())
        # Per-wheel debug overlay for local car
        if const.DEBUG:
            # Draw debug overlays for AI cars
            for ai_car in ai_cars:
                draw_wheel_debug(world_surf, ai_car, 0, 0)
                draw_collision_debug(world_surf, ai_car, self.collision_mesh, 0, 0)
            draw_wheel_debug(world_surf, my_car, 0, 0)
            draw_collision_debug(world_surf, my_car, self.collision_mesh, 0, 0)

        # 5) Draw network/online players' cars
        if stage in ["lobby", "mode1", "mode2"] and draw_remotes:
            for pid, d in remotes.items():
                remote_car_sprites = car_sprites_cache.get(d.get("car_type", "ae86"), car_sprites_cache.get("ae86", []))
                drift_pts = draw_car(world_surf, d["x"], d["y"], d["a"], d.get("name", f"Player{pid}"),
                                     color_body=const.COLOR_BODY_REMOTE,
                                     car_sprites_list=remote_car_sprites,
                                     lights_on=lights_on,
                                     palette_colors=d.get("palette"))
                if pid in self._drift_points_old_remotes and drift_pts is not None:
                    old_pts = self._drift_points_old_remotes[pid]
                    remote_grip = d.get("has_grip", (1.0, 1.0, 1.0, 1.0))
                    for i, grip in enumerate(remote_grip):
                        if i >= len(drift_pts) or i >= len(old_pts):
                            continue
                        if float(grip) >= 0.3:
                            continue
                        slip = max(0.0, min(1.0, 1.0 - float(grip)))
                        alpha = int(60 + 180 * slip)
                        smoke_color = (const.TIRE_MARK_SMOKE[0], const.TIRE_MARK_SMOKE[1], const.TIRE_MARK_SMOKE[2], alpha)
                        pygame.draw.line(self.tire_mark, smoke_color, drift_pts[i], old_pts[i], 3)
                self._drift_points_old_remotes[pid] = tuple(drift_pts) if drift_pts else ()

        return world_surf, resized, False
