"""Abstract base and concrete game mode implementations.

Game modes manage race logic (countdown, checkpoints, laps, leaderboard)
while the main loop in app.py owns physics, rendering and networking.
"""

import time
import math
import pygame
from abc import ABC, abstractmethod

import drift.config.const as const
from drift.core.helpers import clamp


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class BaseGameMode(ABC):
    """Base class for all game modes.

    Subclasses must implement:
      - on_enter()   : called once when stage1 transitions to this mode
      - update()     : called every frame (non-blocking)
      - draw_hud()   : overlay race-specific HUD onto ui_surf
      - on_exit()    : cleanup when leaving the mode
    """

    def __init__(self, checkpoints, total_laps=3):
        self.checkpoints = checkpoints          # list[pygame.Rect]
        self.total_laps = total_laps
        self.active = False
        self.race_time = 0.0                    # seconds since GO

    @abstractmethod
    def on_enter(self, players):
        """Initialise race state.  *players* is a dict mapping
        player_id -> player_info (car object or remote dict)."""

    @abstractmethod
    def update(self, dt, players, my_car, is_host):
        """Per-frame logic.  Returns a dict with optional keys:
        - 'finished': bool  (all players finished)
        - 'stage1':   str   (request a stage transition, e.g. 'leaderboard')
        """

    @abstractmethod
    def draw_hud(self, ui_surf, cam, font_big, font_medium, font_small):
        """Draw mode-specific HUD elements (countdown, lap counter, etc.)."""

    @abstractmethod
    def on_exit(self):
        """Cleanup when leaving the mode."""


# ---------------------------------------------------------------------------
# Player race state (per-player tracking)
# ---------------------------------------------------------------------------

class _PlayerRaceState:
    __slots__ = ("player_id", "current_checkpoint", "current_lap",
                 "finished", "finish_time", "car_type", "name")

    def __init__(self, player_id, car_type="ae86", name=""):
        self.player_id = player_id
        self.current_checkpoint = 0
        self.current_lap = 0
        self.finished = False
        self.finish_time = 0.0
        self.car_type = car_type
        self.name = name


# ---------------------------------------------------------------------------
# SimpleRace  (mode1)
# ---------------------------------------------------------------------------

class SimpleRace(BaseGameMode):
    """Checkpoint-based lap race with countdown, leaderboard, and return-to-lobby."""

    # Countdown phases
    PHASE_COUNTDOWN = "countdown"
    PHASE_RACING    = "racing"
    PHASE_COOLDOWN  = "cooldown" # 5-second wait after all finish
    PHASE_LEADERBOARD = "leaderboard"

    def __init__(self, checkpoints, total_laps=3, start_grid=None, lines=None, local_player_id="local"):
        super().__init__(checkpoints, total_laps)
        self.local_player_id = str(local_player_id)
        self.phase = self.PHASE_COUNTDOWN
        self.countdown_start = 0.0
        self.countdown_duration = 3.0 # seconds
        self.cooldown_start = 0.0
        self.cooldown_duration = 5.0 # seconds
        self.max_time = 10.0 # seconds (2 min race time limit)

        # Optional spawn coordinates from map_meta.json -> "start"
        # expected format: [{"x":..., "y":..., "a":...}, ...]
        self.start_grid = []
        for sp in (start_grid or []):
            try:
                self.start_grid.append((float(sp.get("x", 0.0)), float(sp.get("y", 0.0)), float(sp.get("a", 0.0))))
            except Exception:
                continue

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

        # Per-player state  {player_id: _PlayerRaceState}
        self.player_states: dict[str, _PlayerRaceState] = {}
        self.leaderboard: list[_PlayerRaceState] = []  # ordered by finish time

        # Start-line: first checkpoint position
        self.start_x = 0.0
        self.start_y = 0.0
        if checkpoints:
            cp0 = checkpoints[0]
            self.start_x = cp0.centerx
            self.start_y = cp0.centery

        # Precompute spatial grid for checkpoint hit testing
        self._cp_rects = checkpoints  # already pygame.Rect

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_enter(self, players):
        """players: dict  player_id -> {'car': Car|None, 'car_type': str, 'name': str}"""
        self.active = True
        self.phase = self.PHASE_COUNTDOWN
        self.countdown_start = time.monotonic()
        self.race_time = 0.0
        self.leaderboard.clear()
        self.player_states.clear()

        for pid, info in players.items():
            self.player_states[pid] = _PlayerRaceState(
                pid,
                car_type=info.get("car_type", "ae86"),
                name=info.get("name", pid),
            )

        # Ensure the local player key exists even if caller forgot to include it.
        if self.local_player_id not in self.player_states:
            self.player_states[self.local_player_id] = _PlayerRaceState(self.local_player_id, name="You")

    def on_exit(self):
        self.active = False
        self.player_states.clear()
        self.leaderboard.clear()

    # ------------------------------------------------------------------
    # Per-frame update
    # ------------------------------------------------------------------

    def update(self, dt, players, my_car, is_host):
        """Returns dict with optional 'movement_locked' and 'stage_transition' keys."""
        result = {"movement_locked": False, "stage_transition": None}

        # Keep tracked racers aligned with currently active players.
        self._sync_active_players(players)

        if self.phase == self.PHASE_COUNTDOWN:
            result["movement_locked"] = True
            elapsed = time.monotonic() - self.countdown_start
            if elapsed >= self.countdown_duration:
                self.phase = self.PHASE_RACING
                self.race_time = 0.0
            return result

        if self.phase == self.PHASE_RACING:
            self.race_time += dt
            self._check_checkpoints(players, my_car)

            # Time limit exceeded — force-finish all remaining players
            if self.race_time >= self.max_time:
                for ps in self.player_states.values():
                    if not ps.finished:
                        self._mark_player_finished(ps, self.race_time)
                self.phase = self.PHASE_COOLDOWN
                self.cooldown_start = time.monotonic()
                return result

            # Check if all players finished
            if self.player_states and all(ps.finished for ps in self.player_states.values()):
                self.phase = self.PHASE_COOLDOWN
                self.cooldown_start = time.monotonic()
            return result

        if self.phase == self.PHASE_COOLDOWN:
            result["movement_locked"] = True
            elapsed = time.monotonic() - self.cooldown_start
            if elapsed >= self.cooldown_duration:
                self.phase = self.PHASE_LEADERBOARD
                result["stage_transition"] = "leaderboard"
            return result

        # PHASE_LEADERBOARD — no special update, UI handles it
        result["movement_locked"] = True
        return result

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
            car_type = "ae86"
            info = players.get(pid) if isinstance(players, dict) else None
            if isinstance(info, dict):
                name = info.get("name", pid)
                car_type = info.get("car_type", "ae86")
            self.player_states[pid] = _PlayerRaceState(pid, car_type=car_type, name=name)

        # Drop players who left so they don't block completion.
        for pid in list(self.player_states.keys()):
            if pid not in active_ids:
                self.player_states.pop(pid, None)

        # Keep leaderboard entries only for currently tracked players.
        tracked_ids = set(self.player_states.keys())
        self.leaderboard = [ps for ps in self.leaderboard if ps.player_id in tracked_ids]

    def _mark_player_finished(self, ps: _PlayerRaceState, finish_time: float):
        if ps.finished:
            # Keep best known time if a better authoritative value arrives.
            if finish_time < ps.finish_time:
                ps.finish_time = finish_time
            return

        ps.finished = True
        ps.finish_time = finish_time
        if not any(item.player_id == ps.player_id for item in self.leaderboard):
            self.leaderboard.append(ps)
        self.leaderboard.sort(key=lambda item: item.finish_time)

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
                self.player_states[pid] = _PlayerRaceState(
                    pid,
                    car_type=entry.get("car_type", "ae86"),
                    name=entry.get("name", pid),
                )

            ps = self.player_states[pid]
            ps.name = entry.get("name", ps.name)
            ps.car_type = entry.get("car_type", ps.car_type)
            prev_time = ps.finish_time
            prev_finished = ps.finished
            self._mark_player_finished(ps, finish_time)
            if (not prev_finished) or (ps.finish_time != prev_time):
                changed = True

        if changed:
            self.leaderboard.sort(key=lambda item: item.finish_time)

    def get_local_finish_time(self):
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps is None or not local_ps.finished:
            return None
        return float(local_ps.finish_time)

    # ------------------------------------------------------------------
    # Checkpoint collision
    # ------------------------------------------------------------------

    def _check_checkpoints(self, players, my_car):
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
                if pid == self.local_player_id:
                    my_car.last_checkpoint_coordinates = (my_car.x, my_car.y, my_car.angle)
                ps.current_checkpoint += 1
                # Completed all checkpoints + return to CP0 → lap done
                if ps.current_checkpoint > num_cp:
                    ps.current_lap += 1
                    if ps.current_lap >= self.total_laps:
                        self._mark_player_finished(ps, self.race_time)
                    else:
                        ps.current_checkpoint = 0  # reset for next lap

    # ------------------------------------------------------------------
    # Teleport helpers
    # ------------------------------------------------------------------

    def get_start_positions(self, player_ids):
        """Return {pid: (x, y, a)} start positions.

        Priority:
        1) explicit map start grid from map_meta.json (self.start_grid)
        2) fallback to spread along checkpoint 0
        """
        if self.start_grid:
            positions = {}
            count = len(self.start_grid)
            for i, pid in enumerate(player_ids):
                positions[pid] = self.start_grid[i % count]
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

    # ------------------------------------------------------------------
    # HUD drawing
    # ------------------------------------------------------------------

    def draw_hud(self, ui_surf, cam, font_big, font_medium, font_small):
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
        # LEADERBOARD phase is drawn externally via draw_leaderboard()

    def _draw_finish_banner(self, ui_surf, font_big, font_small):
        """Show confirmation when local player has finished the race."""
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps is None or not local_ps.finished:
            return

        rank = next((i for i, ps in enumerate(self.leaderboard, start=1) if ps.player_id == self.local_player_id), None)
        if rank is None:
            rank_txt = "Finished!"
        else:
            rank_txt = f"Finished! Rank #{rank}"

        mins = int(local_ps.finish_time) // 60
        secs = local_ps.finish_time - mins * 60
        time_txt = f"Time: {mins}:{secs:05.2f}"

        banner = font_big.render(rank_txt, True, (120, 255, 120))
        sub = font_small.render(time_txt, True, const.WHITE_240)
        bx = const.WINDOW_WIDTH // 2 - banner.get_width() // 2
        by = const.TOP_LINE_Y + 36
        sx = const.WINDOW_WIDTH // 2 - sub.get_width() // 2
        sy = by + banner.get_height() + 4

        shadow = font_big.render(rank_txt, True, (0, 0, 0))
        ui_surf.blit(shadow, (bx + 2, by + 2))
        ui_surf.blit(banner, (bx, by))
        ui_surf.blit(sub, (sx, sy))

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

    def _draw_race_hud(self, ui_surf, font_medium, font_small):
        # Timer (top center, below header)
        mins = int(self.race_time) // 60
        secs = self.race_time - mins * 60
        time_str = f"{mins}:{secs:05.2f}"
        time_surf = font_medium.render(time_str, True, const.WHITE_240)
        ui_surf.blit(time_surf, (const.WINDOW_WIDTH // 2 - time_surf.get_width() // 2,
                                  const.TOP_LINE_Y + 8))

        # Per-player lap / checkpoint (left side)
        y = const.TOP_LINE_Y + 40
        local_ps = self.player_states.get(self.local_player_id)
        if local_ps:
            lap_str = f"Lap {min(local_ps.current_lap + 1, self.total_laps)}/{self.total_laps}"
            cp_str = f"CP {local_ps.current_checkpoint}/{len(self._cp_rects)}"
            lap_surf = font_small.render(lap_str, True, const.WHITE_240)
            cp_surf = font_small.render(cp_str, True, const.GREY_200)
            ui_surf.blit(lap_surf, (12, y))
            ui_surf.blit(cp_surf, (12, y + 20))

    def _draw_cooldown_banner(self, ui_surf, font_big):
        elapsed = time.monotonic() - self.cooldown_start
        remaining = max(0, self.cooldown_duration - elapsed)
        text = f"Race finished! Leaderboard in {remaining:.0f}s"
        surf = font_big.render(text, True, (80, 255, 80))
        x = const.WINDOW_WIDTH // 2 - surf.get_width() // 2
        y = const.WINDOW_HEIGHT // 3
        shadow = font_big.render(text, True, (0, 0, 0))
        ui_surf.blit(shadow, (x + 2, y + 2))
        ui_surf.blit(surf, (x, y))

    # ------------------------------------------------------------------
    # Leaderboard rendering (called when phase == LEADERBOARD)
    # ------------------------------------------------------------------

    def draw_leaderboard(self, ui_surf, font_big, font_medium, font_small, is_host):
        """Draw the full leaderboard scene. Returns dict with optional 'return_btn_rect'."""
        result = {}

        # Semi-transparent background
        overlay = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 10, 20, 210))
        ui_surf.blit(overlay, (0, 0))

        # Title
        title = font_big.render("LEADERBOARD", True, (255, 220, 80))
        ui_surf.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, 60))

        # Column headers
        col_rank_x = const.WINDOW_WIDTH // 2 - 250
        col_name_x = col_rank_x + 70
        col_car_x = col_name_x + 180
        col_time_x = col_car_x + 140
        header_y = 120

        for label, lx in [("Rank", col_rank_x), ("Player", col_name_x),
                           ("Car", col_car_x), ("Time", col_time_x)]:
            hdr = font_medium.render(label, True, const.GREY_200)
            ui_surf.blit(hdr, (lx, header_y))

        # Rows
        row_y = header_y + 40
        for rank, ps in enumerate(self.leaderboard, start=1):
            color = (255, 215, 0) if rank == 1 else (200, 200, 200) if rank == 2 else (180, 140, 100) if rank == 3 else const.WHITE_240
            if ps.finish_time < self.max_time: rank_s = font_medium.render(f"#{rank}", True, color)
            else: rank_s = font_medium.render(f"DNF", True, const.WHITE_240)
            name_s = font_medium.render(ps.name[:16], True, const.WHITE_240)
            car_s = font_medium.render(ps.car_type, True, const.GREY_200)
            mins = int(ps.finish_time) // 60
            secs = ps.finish_time - mins * 60
            time_str = f"{mins}:{secs:05.2f}" if ps.finish_time < self.max_time else "DNF"
            time_s = font_medium.render(time_str, True, const.WHITE_240)

            ui_surf.blit(rank_s, (col_rank_x, row_y))
            ui_surf.blit(name_s, (col_name_x, row_y))
            ui_surf.blit(car_s, (col_car_x, row_y))
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
