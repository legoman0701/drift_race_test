import time, math, pygame
import drift.config.const as const
from drift.gamemodes.template import BaseGameMode, PlayerRaceState

class BestLap(BaseGameMode):
    """player with best single lap time wins"""

    def __init__(self, checkpoints, start_grid=None, choice_index=2, lines=None, local_player_id="local", path_poly=None):
        super().__init__(checkpoints, start_grid)
        self.phase = self.PHASE_COUNTDOWN
        self.countdown_start = 0.0
        self.countdown_duration = 3.0 # seconds
        self.cooldown_start = 0.0
        self.cooldown_duration = 5.0 # seconds
        self.max_time = const.MODES_CHOICES[const.MODE_INDEX][choice_index]
        self.max_players = 6
        self.local_player_id = str(local_player_id)

        # Optional finish lines from map_meta.json -> "lines"
        # expected format: [{"id": ..., "start": [x, y], "end": [x, y]}, ...]
        self._cp_lines: dict[int, dict] = {}
        for line in (lines or []):
            try:
                lid = int(line["id"])
                self._cp_lines[lid] = {
                    "start": (float(line["start"][0]), float(line["start"][1])),
                    "end":   (float(line["end"][0]),   float(line["end"][1])),
                }
            except Exception:
                continue

        # Start-line: first checkpoint position
        self.start_x = 0.0
        self.start_y = 0.0
        if checkpoints:
            cp0 = checkpoints[0]
            self.start_x = cp0.centerx
            self.start_y = cp0.centery

        # Precompute spatial grid for checkpoint hit testing
        self._cp_rects = checkpoints  # already pygame.Rect

        # Optional AI polypath for tangent-based respawn orientation
        self._path_poly = list(path_poly) if path_poly else []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_enter(self, players):
        super().on_enter(players, self.local_player_id)
        self.countdown_start = time.monotonic()
        # Initialize lap start times to zero
        for ps in self.player_states.values():
            ps._lap_start_time = 0.0

    def update(self, dt, players, my_car, is_host=False): # per frame upadte
        """Returns dict with optional 'movement_locked' and 'stage_transition' keys."""
        result = {"movement_locked": False, "stage_transition": None}

        # Keep tracked racers aligned with currently active players.
        self._sync_active_players(players)

        if self.phase == self.PHASE_COUNTDOWN: # 3 2 1 go phase
            result["movement_locked"] = True
            elapsed = time.monotonic() - self.countdown_start
            if elapsed >= self.countdown_duration:
                self.phase = self.PHASE_RACING
                self.race_time = 0.0 # start timer
                # mark lap start for all players when racing begins
                for ps in self.player_states.values():
                    ps._lap_start_time = 0.0
            return result

        if self.phase == self.PHASE_RACING: # race phase
            self.race_time += dt
            self._check_checkpoints(players, my_car)

            if self.race_time >= self.max_time: # timer runs out
                for ps in self.player_states.values():
                    if not ps.finished:
                        self._mark_player_finished(ps, self.race_time)
                self.phase = self.PHASE_COOLDOWN
                self.cooldown_start = time.monotonic()
                return result

            # Check if all players finished
            # if self.player_states and all(ps.finished for ps in self.player_states.values()):
            #     self.phase = self.PHASE_COOLDOWN
            #     self.cooldown_start = time.monotonic()
            return result

        if self.phase == self.PHASE_COOLDOWN: # cooldown before lb phase
            result["movement_locked"] = True
            elapsed = time.monotonic() - self.cooldown_start
            if elapsed >= self.cooldown_duration:
                self.phase = self.PHASE_LEADERBOARD
                result["stage_transition"] = "leaderboard"
            return result

        # PHASE_LEADERBOARD — no special update, UI handles it
        result["movement_locked"] = True
        return result

    def _mark_player_finished(self, ps: PlayerRaceState, finish_time: float):
        if ps.finished:
            # Keep best known time if a better authoritative value arrives.
            if finish_time < ps.finish_time:
                ps.finish_time = finish_time
            return

        ps.finished = True
        ps.finish_time = finish_time
        if not any(item.player_id == ps.player_id for item in self.leaderboard):
            self.leaderboard.append(ps)
        self.sort_leaderboard()

    def _check_checkpoints(self, players, my_car): # checkpoints collision
        """Test each active player against their next expected checkpoint."""
        if not self._cp_rects:
            return
        num_cp = len(self._cp_rects)

        # Build lookup:  player_id -> (x, y)
        positions = {}
        # Local player
        positions[self.local_player_id] = (my_car.x, my_car.y)
        # Remote / AI
        for pid, info in players.items():
            if hasattr(info, "x"):
                positions[pid] = (info.x, info.y)
            elif isinstance(info, dict):
                positions[pid] = (info.get("x", 0), info.get("y", 0))

        for pid, ps in self.player_states.items():
            if ps.finished:
                continue
            pos = positions.get(pid)
            if pos is None:
                continue

            expected_cp = ps.current_checkpoint
            # After all N checkpoints, player must return to CP0 to finish the lap
            if expected_cp > num_cp:
                continue

            # When expected_cp == num_cp, test against CP0 (the finish line)
            rect = self._cp_rects[0] if expected_cp == num_cp else self._cp_rects[expected_cp]
            if rect.collidepoint(pos[0], pos[1]):
                current_idx = 0 if expected_cp == num_cp else expected_cp
                rx = float(self._cp_rects[current_idx].centerx)
                ry = float(self._cp_rects[current_idx].centery)
                tangent = self._tangent_angle_at(rx, ry)
                if tangent is not None:
                    ra = tangent
                elif num_cp > 1:
                    next_idx = (current_idx + 1) % num_cp
                    ra = math.atan2(
                        float(self._cp_rects[next_idx].centery) - ry,
                        float(self._cp_rects[next_idx].centerx) - rx,
                    )
                else:
                    ra = my_car.angle if pid == self.local_player_id else 0.0
                respawn_coords = (rx, ry, ra)
                if pid == self.local_player_id:
                    my_car.last_checkpoint_coordinates = respawn_coords
                else:
                    car_obj = players.get(pid)
                    if hasattr(car_obj, 'last_checkpoint_coordinates'):
                        car_obj.last_checkpoint_coordinates = respawn_coords
                ps.current_checkpoint += 1
                # Completed all checkpoints + return to CP0 → lap done
                if ps.current_checkpoint > num_cp:
                    ps.current_lap += 1
                    # Track best lap time
                    lap_time = self.race_time - ps._lap_start_time
                    if ps.best_lap_time is None or lap_time < ps.best_lap_time:
                        ps.best_lap_time = lap_time
                    ps._lap_start_time = self.race_time
                    # if ps.current_lap >= self.total_laps:
                    #     self._mark_player_finished(ps, self.race_time)
                    # else:
                    ps.current_checkpoint = 0  # reset for next lap

    def _tangent_angle_at(self, x, y): # path tangent helper for respawn orientation
        """Return the path tangent angle (radians) at the point on _path_poly
        closest to (x, y).  Falls back to None if the path is not available."""
        poly = self._path_poly
        if len(poly) < 2:
            return None
        best_d2 = float("inf")
        best_ax, best_ay, best_bx, best_by = poly[0][0], poly[0][1], poly[1][0], poly[1][1]
        n = len(poly)
        for i in range(n - 1):
            ax, ay, _ = poly[i]
            bx, by, _ = poly[i + 1]
            vx, vy = bx - ax, by - ay
            denom = vx * vx + vy * vy
            if denom == 0:
                continue
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / denom))
            cx, cy = ax + vx * t, ay + vy * t
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_ax, best_ay, best_bx, best_by = ax, ay, bx, by
        return math.atan2(best_by - best_ay, best_bx - best_ax)

    def sort_leaderboard(self):
        self.leaderboard.sort(key=lambda item: item.best_lap_time if item.best_lap_time is not None else float("inf"))

    # ------------------------------------------------------------------
    # drawing
    # ------------------------------------------------------------------

    def draw_hud(self, ui_surf, cam, font_big, font_medium, font_small): # 
        self.draw_checkpoints(ui_surf, cam, player_id=self.local_player_id)
        if self.phase == self.PHASE_COUNTDOWN:
            self._draw_countdown(ui_surf, font_big)
        elif self.phase == self.PHASE_RACING:
            self._draw_race_hud(ui_surf, font_medium, font_small)
            self._draw_finish_banner(ui_surf, font_big, font_small)
        elif self.phase == self.PHASE_COOLDOWN:
            self._draw_race_hud(ui_surf, font_medium, font_small)
            self._draw_finish_banner(ui_surf, font_big, font_small)
            self._draw_cooldown_banner(ui_surf, font_big)

    def draw_checkpoints(self, ui_surf, cam, player_id=None, color=(0, 255, 0)):
        """Draw only the next checkpoint required by *player_id*.

        This keeps mode1 visuals focused: only one target checkpoint is visible.
        If lines data is available for the checkpoint, a line is drawn instead of a rect.
        """
        if player_id is None:
            player_id = self.local_player_id
        if not self._cp_rects:
            return
        ps = self.player_states.get(player_id)
        if ps is None or ps.finished:
            return
        num_cp = len(self._cp_rects)
        cp_idx = ps.current_checkpoint
        # When waiting for the finish (CP0 again), draw CP0's indicator
        if cp_idx == num_cp:
            cp_idx = 0
        elif cp_idx < 0 or cp_idx >= num_cp:
            return

        line_data = self._cp_lines.get(cp_idx)
        if line_data:
            sx, sy = line_data["start"]
            ex, ey = line_data["end"]
            x1 = int((sx - cam.x) * cam.zoom + const.WINDOW_WIDTH / 2)
            y1 = int((sy - cam.y) * cam.zoom + const.WINDOW_HEIGHT / 2)
            x2 = int((ex - cam.x) * cam.zoom + const.WINDOW_WIDTH / 2)
            y2 = int((ey - cam.y) * cam.zoom + const.WINDOW_HEIGHT / 2)
            pygame.draw.line(ui_surf, color, (x1, y1), (x2, y2), 3)
        else:
            rect = self._cp_rects[cp_idx]
            rel_x = rect.x - cam.x
            rel_y = rect.y - cam.y
            screen_x = int(rel_x * cam.zoom + const.WINDOW_WIDTH / 2)
            screen_y = int(rel_y * cam.zoom + const.WINDOW_HEIGHT / 2)
            width = int(rect.width * cam.zoom)
            height = int(rect.height * cam.zoom)
            draw_rect = pygame.Rect(screen_x, screen_y, width, height)
            if ui_surf.get_rect().colliderect(draw_rect):
                pygame.draw.rect(ui_surf, color, draw_rect, 3)

    def _draw_finish_banner(self, ui_surf, font_big, font_small):
        """Show confirmation when local player has finished the race."""
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps is None or not local_ps.finished:
            return

        rank = next((i for i, ps in enumerate(self.leaderboard, start=1) if ps.player_id == self.local_player_id), None)
        rank_txt = "Finished!" if rank is None else f"Finished! Rank #{rank}"

        # mins = int(local_ps.finish_time) // 60
        # secs = local_ps.finish_time - mins * 60
        # time_txt = f"Time: {mins}:{secs:05.2f}"

        banner = font_big.render(rank_txt, True, (120, 255, 120))
        # sub = font_small.render(time_txt, True, const.WHITE_240)
        bx = const.WINDOW_WIDTH // 2 - banner.get_width() // 2
        by = const.TOP_LINE_Y + 136
        # sx = const.WINDOW_WIDTH // 2 - sub.get_width() // 2
        # sy = by + banner.get_height() + 4

        shadow = font_big.render(rank_txt, True, (0, 0, 0))
        ui_surf.blit(shadow, (bx + 2, by + 2))
        ui_surf.blit(banner, (bx, by))
        # ui_surf.blit(sub, (sx, sy))

    def _draw_race_hud(self, ui_surf, font_medium, font_small):
        # remaining timer
        remaining_timer = self.max_time - self.race_time
        if remaining_timer < 0: remaining_timer = 0.0
        mins = int(remaining_timer) // 60
        secs = remaining_timer - mins * 60
        remaining_timer_str = f"{mins}:{secs:05.2f}"
        remaining_timer_surf = font_medium.render(remaining_timer_str, True, const.WHITE_240)
        ui_surf.blit(remaining_timer_surf, (const.WINDOW_WIDTH // 2 - remaining_timer_surf.get_width() // 2,
                                             const.TOP_LINE_Y + 8))
        # current lap timer
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps:
            current_time_str = self.race_time - local_ps._lap_start_time
            mins = int(current_time_str) // 60
            secs = current_time_str - mins * 60
            lap_time_str = f"Lap: {mins}:{secs:05.2f}"
            lap_time_surf = font_medium.render(lap_time_str, True, const.WHITE_240)
            ui_surf.blit(lap_time_surf, (const.WINDOW_WIDTH // 2 - lap_time_surf.get_width() // 2,
                                     const.TOP_LINE_Y + remaining_timer_surf.get_height() * 2))
        # best lap timer
        if local_ps and local_ps.best_lap_time is not None:
            best_time_str = f"Best: {local_ps.best_lap_time:.2f}"
            best_time_surf = font_medium.render(best_time_str, True, const.WHITE_240)
            ui_surf.blit(best_time_surf, (const.WINDOW_WIDTH // 2 - best_time_surf.get_width() // 2,
                                      const.TOP_LINE_Y + remaining_timer_surf.get_height() * 3 + lap_time_surf.get_height()))

        # Per-player lap / checkpoint (left side)
        y = const.TOP_LINE_Y + 40
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps:
            lap_str = f"Lap {local_ps.current_lap + 1}"
            cp_str = f"CP {local_ps.current_checkpoint}/{len(self._cp_rects)}"
            lap_surf = font_small.render(lap_str, True, const.WHITE_240)
            cp_surf = font_small.render(cp_str, True, const.WHITE_240)
            ui_surf.blit(lap_surf, (12, y))
            ui_surf.blit(cp_surf, (12, y + 20))
