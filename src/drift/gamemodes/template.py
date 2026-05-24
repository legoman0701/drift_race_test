import time, math, pygame
from abc import ABC, abstractmethod
import drift.config.const as const

class PlayerRaceState:
    __slots__ = ("player_id", "current_checkpoint", "current_lap",
                 "finished", "finish_time", "car_type", "name",
                 "best_lap_time", "_lap_start_time")

    def __init__(self, player_id, car_type="911", name=""):
        self.player_id = player_id
        self.current_checkpoint = 0
        self.current_lap = 0
        self.finished = False
        self.finish_time = 0.0
        self.car_type = car_type
        self.name = name
        self.best_lap_time = None   # float | None
        self._lap_start_time = 0.0  # race_time when current lap began

class BaseGameMode(ABC):
    """Base class for all game modes.

    Subclasses must implement:
      - on_enter()   : called once when stage1 transitions to this mode
      - update()     : called every frame (non-blocking)
      - draw_hud()   : overlay race-specific HUD onto ui_surf
      - on_exit()    : cleanup when leaving the mode
    """
    
    # Countdown phases
    PHASE_COUNTDOWN = "countdown"
    PHASE_RACING    = "racing"
    PHASE_COOLDOWN  = "cooldown" # 5-second wait after all finish
    PHASE_LEADERBOARD = "leaderboard"

    def __init__(self, checkpoints, start_grid=None):
        self.checkpoints = checkpoints # list[pygame.Rect]
        self.active = False # is race active
        self.sorted = False # has lb been sorted
        self.race_time = 0.0 # seconds since the GO
        self.player_states: dict[str, PlayerRaceState] = {} # player_id -> _PlayerRaceState
        self.leaderboard: list[PlayerRaceState] = []  # should be sorted

        # Optional spawn coordinates from map_meta.json -> "start"
        # expected format: [{"x":..., "y":..., "a":...}, ...]
        self.start_grid = []
        for sp in (start_grid or []):
            try:
                self.start_grid.append((float(sp.get("x", 0.0)), float(sp.get("y", 0.0)), float(sp.get("a", 0.0))))
            except Exception:
                continue

    def on_enter(self, players, local_player_id="local"):
        """players: dict  player_id -> {'car': Car|None, 'car_type': str, 'name': str}"""
        self.active = True
        self.phase = self.PHASE_COUNTDOWN
        self.race_time = 0.0
        self.leaderboard.clear()
        self.player_states.clear()

        for pid, info in players.items():
            self.player_states[pid] = PlayerRaceState(
                pid,
                car_type=info.get("car_type", "911"),
                name=info.get("name", pid),
            )

        # Ensure the local player key exists even if caller forgot to include it.
        if local_player_id not in self.player_states:
            self.player_states[local_player_id] = PlayerRaceState(local_player_id, name="You")

    def on_exit(self):
        self.active = False
        self.leaderboard.clear()
        self.player_states.clear()
        const.AI_PATH_FOLLOW = False
        const.CURSOR_FOLLOW = False

    @abstractmethod
    def update(self, dt, players, my_car, is_host=False):
        """Per-frame logic.  Returns a dict with optional keys:
        - 'finished': bool  (all players finished)
        - 'stage1':   str   (request a stage transition, e.g. 'leaderboard')
        """

    def get_start_positions(self, player_ids): # tp helper for start
        """Return {pid: (x, y, a)} start positions.

        Priority:
        1) explicit map start grid from map_meta.json (self.start_grid)
        2) fallback to spread along checkpoint 0
        """
        if self.start_grid:
            positions = {}
            count = len(self.start_grid)
            for i, pid in enumerate(player_ids):
                bx, by, ba = self.start_grid[i % count]
                # Offset wrapped players so they don't overlap
                wrap = i // count
                if wrap > 0:
                    bx += wrap * 40.0
                    by += wrap * 40.0
                positions[pid] = (bx, by, ba)
            return positions

        if not self._cp_rects:
            return {pid: (400, 400, 0.0) for pid in player_ids}

        cp0 = self._cp_rects[0]
        # Spread players along the longer axis of checkpoint 0
        horizontal = cp0.width >= cp0.height
        positions = {}
        count = max(1, len(player_ids))
        for i, pid in enumerate(player_ids):
            frac = (i + 1) / (count + 1)
            if horizontal:
                x = cp0.x + cp0.width * frac
                y = cp0.centery
            else:
                x = cp0.centerx
                y = cp0.y + cp0.height * frac
            positions[pid] = (x, y, 0.0)
        return positions

    # ---------- network ----------

    def _sync_active_players(self, players):
        """Add newcomers and remove disconnected players from race tracking."""
        active_ids = {self.local_player_id}
        if isinstance(players, dict):
            active_ids.update(players.keys())

        # Add newly observed players.
        for pid in active_ids:
            if pid in self.player_states:
                continue
            name = pid
            car_type = "911"
            info = players.get(pid) if isinstance(players, dict) else None
            if isinstance(info, dict):
                name = info.get("name", pid)
                car_type = info.get("car_type", "911")
            self.player_states[pid] = PlayerRaceState(pid, car_type=car_type, name=name)

        # Drop players who left so they don't block completion.
        for pid in list(self.player_states.keys()):
            if pid not in active_ids:
                self.player_states.pop(pid, None)

        # Keep leaderboard entries only for currently tracked players.
        tracked_ids = set(self.player_states.keys())
        self.leaderboard = [ps for ps in self.leaderboard if ps.player_id in tracked_ids]

    def apply_network_results(self, results):
        """Merge authoritative/shared finish times received from networking."""
        if not isinstance(results, dict):
            return

        changed = False
        for pid, entry in results.items():
            if not isinstance(entry, dict):
                continue
            try:
                finish_time = float(entry.get("time", 0.0))
            except Exception:
                continue
            if finish_time < 0.0:
                continue

            if pid not in self.player_states:
                self.player_states[pid] = PlayerRaceState(
                    pid,
                    car_type=entry.get("car_type", "911"),
                    name=entry.get("name", pid),
                )

            ps = self.player_states[pid]
            ps.name = entry.get("name", ps.name)
            ps.car_type = entry.get("car_type", ps.car_type)
            # Apply best lap time if present in networked results
            try:
                if "best_lap" in entry and entry["best_lap"] is not None:
                    b = float(entry.get("best_lap"))
                    if b >= 0.0:
                        ps.best_lap_time = b
            except Exception:
                pass
            prev_time = ps.finish_time
            prev_finished = ps.finished
            self._mark_player_finished(ps, finish_time)
            if (not prev_finished) or (ps.finish_time != prev_time):
                changed = True

        if changed:
            self.sort_leaderboard()

    def get_local_finish_time(self):
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps is None or not local_ps.finished:
            return None
        return float(local_ps.finish_time)

    # ---------- leaderboard ----------

    def force_end_race(self, max_time_fallback=9999.0):
        """stop the race and push all active players to the leaderboard."""
        self.phase = self.PHASE_COOLDOWN
        self.cooldown_start = time.monotonic()

        for ps in self.player_states.values():
            if not ps.finished:
                ps.finished = True
                # ps.finish_time = dnf_time
                if not any(item.player_id == ps.player_id for item in self.leaderboard):
                    self.leaderboard.append(ps)
                    
        # self.sort_leaderboard()
        # self.sorted = True

    @abstractmethod
    def sort_leaderboard(self):
        """Sort the leaderboard."""

    def draw_leaderboard(self, ui_surf, font_big, font_medium, font_small, is_host):
        if not self.sorted:
            self.sort_leaderboard()
            self.sorted = True

        result = {}

        # Semi-transparent background
        overlay = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 10, 20, 210))
        ui_surf.blit(overlay, (0, 0))

        # Title
        title = font_big.render("LEADERBOARD", True, (255, 220, 80))
        ui_surf.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, 60))

        # Column headers
        col_rank_x = const.WINDOW_WIDTH // 2 - 300
        col_name_x = col_rank_x + 70
        col_car_x = col_name_x + 170
        col_best_x = col_car_x + 120
        col_time_x = col_best_x + 120
        header_y = 120

        for label, lx in [("Rank", col_rank_x), ("Player", col_name_x),
                           ("Car", col_car_x), ("Best Lap", col_best_x), ("Time", col_time_x)]:
            hdr = font_medium.render(label, True, const.GREY_200)
            ui_surf.blit(hdr, (lx, header_y))

        # if not self.player_states: print("empty player states from draw_leaderboard located in template.py")
        # self._sync_active_players(self.player_states)

        # Rows
        row_y = header_y + 40
        for rank, ps in enumerate(self.leaderboard, start=1):
            # print("someone ? from draw_leaderboard located in template.py")
            color = (255, 215, 0) if rank == 1 else (200, 200, 200) if rank == 2 else (180, 140, 100) if rank == 3 else const.WHITE_240
            # if ps.finish_time < self.max_time: rank_s = font_medium.render(f"#{rank}", True, color)
            # else: rank_s = font_medium.render(f"DNF", True, const.WHITE_240)
            rank_s = font_medium.render(f"#{rank}", True, color)
            name_s = font_medium.render(ps.name[:16], True, const.WHITE_240)
            car_s = font_medium.render(ps.car_type, True, const.GREY_200)
            if ps.best_lap_time is not None:
                bl_mins = int(ps.best_lap_time) // 60
                bl_secs = ps.best_lap_time - bl_mins * 60
                best_str = f"{bl_mins}:{bl_secs:05.2f}"
            else:
                best_str = "-"
            best_s = font_medium.render(best_str, True, (180, 220, 255))
            # print(ps.finish_time)
            mins = int(self.race_time) // 60
            secs = self.race_time - mins * 60
            time_str = f"{mins}:{secs:05.2f}" # if ps.finish_time < self.max_time else "DNF"
            time_s = font_medium.render(time_str, True, const.WHITE_240)

            ui_surf.blit(rank_s, (col_rank_x, row_y))
            ui_surf.blit(name_s, (col_name_x, row_y))
            ui_surf.blit(car_s, (col_car_x, row_y))
            ui_surf.blit(best_s, (col_best_x, row_y))
            ui_surf.blit(time_s, (col_time_x, row_y))
            row_y += 36

        # "Return to Lobby" button — host only
        if is_host:
            btn_w, btn_h = 260, 50
            btn_x = const.WINDOW_WIDTH // 2 - btn_w // 2
            btn_y = const.WINDOW_HEIGHT - 100
            btn_rect = pygame.Rect(btn_x, btn_y, btn_w, btn_h)

            mouse_pos = pygame.mouse.get_pos()
            hover = btn_rect.collidepoint(mouse_pos)
            btn_color = (60, 180, 60) if hover else (50, 150, 50)
            pygame.draw.rect(ui_surf, btn_color, btn_rect, border_radius=8)
            pygame.draw.rect(ui_surf, const.WHITE_240, btn_rect, 2, border_radius=8)

            lbl = font_medium.render("Return to Lobby", True, const.WHITE_240)
            ui_surf.blit(lbl, (btn_rect.centerx - lbl.get_width() // 2,
                               btn_rect.centery - lbl.get_height() // 2))
            result["return_btn_rect"] = btn_rect

        return result

    # ---------- draw hud ----------

    @abstractmethod
    def draw_hud(self, ui_surf, cam, font_big, font_medium, font_small, show_timers=True, show_countdown=True):
        """Draw mode-specific HUD elements (countdown, lap counter, etc.)."""

    def _draw_countdown(self, ui_surf, font_big):
        elapsed = time.monotonic() - self.countdown_start
        remaining = self.countdown_duration - elapsed
        if remaining > 0:
            number = max(1, math.ceil(remaining))
            text = str(number)
            color = (255, 255, 80)
        else:
            text = "GO!"
            color = (80, 255, 80)

        surf = font_big.render(text, True, color)
        x = const.WINDOW_WIDTH // 2 - surf.get_width() // 2
        y = const.WINDOW_HEIGHT // 3 - surf.get_height() // 2
        # Dark shadow for readability
        shadow = font_big.render(text, True, (0, 0, 0))
        ui_surf.blit(shadow, (x + 2, y + 2))
        ui_surf.blit(surf, (x, y))

    def _draw_cooldown_banner(self, ui_surf, font_big):
        elapsed = time.monotonic() - self.cooldown_start
        remaining = max(0, self.cooldown_duration - elapsed)
        text = f"Race finished! Leaderboard in {remaining:.0f}s"
        surf = font_big.render(text, True, (80, 255, 80))
        x = const.WINDOW_WIDTH // 2 - surf.get_width() // 2
        y = const.WINDOW_HEIGHT * 0.45
        shadow = font_big.render(text, True, (0, 0, 0))
        ui_surf.blit(shadow, (x + 2, y + 2))
        ui_surf.blit(surf, (x, y))

