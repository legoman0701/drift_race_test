import time

import pygame

import drift.config.const as const
from drift.gamemodes.classicrace import ClassicRace


class DriftAngleRace(ClassicRace):
    """Timed drift mode with combo banking and score-based leaderboard."""

    def __init__(self, checkpoints, start_grid=None, choice_index=2, lines=None, local_player_id="local", path_poly=None):
        super().__init__(checkpoints, start_grid=start_grid, choice_index=choice_index, lines=lines,
                         local_player_id=local_player_id, path_poly=path_poly)

        self.max_time = float(const.MODES_CHOICES[const.MODE_INDEX][choice_index])

        # Local HUD-facing fields.
        self.current_drift_angle_deg = 0.0
        self.current_drift_multiplier = 1.0
        self.drift_score = 0.0
        self.local_drift_score = 0.0
        self._real_drift_active = False
        
        # Per-player drift state.
        self.player_drift_scores = {}
        self.player_combo_scores = {}
        self.player_active_sides = {}
        self.player_real_drift = {}

        # Drift validity thresholds.
        self._min_drift_angle_deg = 10.0
        self._min_speed = 14.0
        self._spinout_yaw_rate = 2.8
        self._spinout_angle_deg = 70.0
        self._crash_impact_speed = 5.0

    def on_enter(self, players):
        super().on_enter(players)
        self.current_drift_angle_deg = 0.0
        self.current_drift_multiplier = 1.0
        self.drift_score = 0.0
        self.local_drift_score = 0.0
        self._real_drift_active = False

        ids = list(self.player_states.keys())
        self.player_drift_scores = {pid: 0.0 for pid in ids}
        self.player_combo_scores = {pid: 0.0 for pid in ids}
        self.player_active_sides = {pid: 0 for pid in ids}
        self.player_real_drift = {pid: False for pid in ids}

    def get_pb(self):
        return round(self.drift_score / (self.race_time or 1), 2)

    def _ensure_player_buckets(self):
        for pid in self.player_states.keys():
            self.player_drift_scores.setdefault(pid, 0.0)
            self.player_combo_scores.setdefault(pid, 0.0)
            self.player_active_sides.setdefault(pid, 0)
            self.player_real_drift.setdefault(pid, False)

    def _drift_side(self, angle_deg):
        if angle_deg > 0.0:
            return 1
        if angle_deg < 0.0:
            return -1
        return 0

    def _is_real_drift(self, car_obj, angle_deg):
        speed = (float(getattr(car_obj, "vx", 0.0)) ** 2 + float(getattr(car_obj, "vy", 0.0)) ** 2) ** 0.5
        if speed < self._min_speed:
            return False
        if abs(angle_deg) < self._min_drift_angle_deg:
            return False

        grips = getattr(car_obj, "has_grip", None)
        if not isinstance(grips, (tuple, list)) or len(grips) < 4:
            return False

        wheels_low_grip = 0
        for g in grips[:4]:
            if float(g) < 0.5:
                wheels_low_grip += 1
        return wheels_low_grip >= 2

    def _bank_player_score(self, pid):
        combo = self.player_combo_scores.get(pid, 0.0)
        if combo > 0.0:
            self.player_drift_scores[pid] = self.player_drift_scores.get(pid, 0.0) + combo
        self.player_combo_scores[pid] = 0.0
        self.player_active_sides[pid] = 0

    def _bank_all_scores(self):
        for pid in list(self.player_states.keys()):
            self._bank_player_score(pid)

    def _update_player_drift(self, pid, car_obj, dt):
        angle = float(getattr(car_obj, "drift_angle_degrees", 0.0))
        mult = float(getattr(car_obj, "drift_multiplier", 1.0))
        impact_speed = float(getattr(car_obj, "last_impact_speed", 0.0))
        yaw_rate = abs(float(getattr(car_obj, "v_angle", 0.0)))

        spinout = yaw_rate >= self._spinout_yaw_rate or abs(angle) >= self._spinout_angle_deg
        crashed = impact_speed >= self._crash_impact_speed

        if self.player_combo_scores.get(pid, 0.0) > 0.0 and (spinout or crashed):
            self.player_combo_scores[pid] = 0.0
            self.player_active_sides[pid] = 0
            self.player_real_drift[pid] = False
            return angle, mult

        drifting = self._is_real_drift(car_obj, angle)
        self.player_real_drift[pid] = drifting
        side = self._drift_side(angle)

        if drifting and side != 0:
            active_side = self.player_active_sides.get(pid, 0)
            if active_side == 0:
                self.player_active_sides[pid] = side
            elif side != active_side:
                self._bank_player_score(pid)
                self.player_active_sides[pid] = side

            self.player_combo_scores[pid] = self.player_combo_scores.get(pid, 0.0) + abs(angle) * mult * dt
        else:
            self._bank_player_score(pid)

        return angle, mult

    def _finish_all_players(self):
        for ps in self.player_states.values():
            if ps.finished:
                continue
            ps.finished = True
            ps.finish_time = self.race_time
            if not any(item.player_id == ps.player_id for item in self.leaderboard):
                self.leaderboard.append(ps)

    def update(self, dt, players, my_car, is_host=False):
        result = {"movement_locked": False, "stage_transition": None}

        self._sync_active_players(players)
        self._ensure_player_buckets()

        if self.phase == self.PHASE_COUNTDOWN:
            result["movement_locked"] = True
            elapsed = time.monotonic() - self.countdown_start
            if elapsed >= self.countdown_duration:
                self.phase = self.PHASE_RACING
                self.race_time = 0.0
            return result

        if self.phase == self.PHASE_RACING:
            self.race_time += dt

            # Consume network-replicated drift scores from remote state dicts.
            if isinstance(players, dict):
                for pid, info in players.items():
                    if not isinstance(info, dict):
                        continue
                    try:
                        score = info.get("drift_score")
                        if score is None:
                            continue
                        score_val = float(score)
                        if score_val >= 0.0:
                            self.player_drift_scores[pid] = max(self.player_drift_scores.get(pid, 0.0), score_val)
                    except Exception:
                        continue

            # Build an object map for players whose drift telemetry is available.
            car_objs = {self.local_player_id: my_car}
            if isinstance(players, dict):
                for pid, obj in players.items():
                    if hasattr(obj, "drift_angle_degrees"):
                        car_objs[pid] = obj

            for pid in list(self.player_states.keys()):
                car_obj = car_objs.get(pid)
                if car_obj is None:
                    continue
                angle, mult = self._update_player_drift(pid, car_obj, dt)

                if pid == self.local_player_id:
                    self.current_drift_angle_deg = angle
                    self.current_drift_multiplier = mult
                    self._real_drift_active = self.player_real_drift.get(pid, False)

            # Sync local HUD totals from per-player state.
            self.drift_score = self.player_drift_scores.get(self.local_player_id, 0.0)
            self.local_drift_score = self.player_combo_scores.get(self.local_player_id, 0.0)

            if self.race_time >= self.max_time:
                self._bank_all_scores()
                self.drift_score = self.player_drift_scores.get(self.local_player_id, 0.0)
                self.local_drift_score = 0.0
                self._finish_all_players()
                self.phase = self.PHASE_COOLDOWN
                self.cooldown_start = time.monotonic()

            return result

        if self.phase == self.PHASE_COOLDOWN:
            result["movement_locked"] = True
            elapsed = time.monotonic() - self.cooldown_start
            if elapsed >= self.cooldown_duration:
                self.phase = self.PHASE_LEADERBOARD
                self.sort_leaderboard()
                self.sorted = True
                result["stage_transition"] = "leaderboard"
            return result

        result["movement_locked"] = True
        return result

    def sort_leaderboard(self):
        self.leaderboard.sort(
            key=lambda ps: (
                -self.player_drift_scores.get(ps.player_id, 0.0),
                ps.finish_time if ps.finish_time is not None else float("inf"),
            )
        )

    def apply_network_results(self, results):
        super().apply_network_results(results)
        if not isinstance(results, dict):
            return
        changed = False
        for pid, entry in results.items():
            if not isinstance(entry, dict):
                continue
            try:
                if "drift_score" in entry and entry["drift_score"] is not None:
                    score = float(entry.get("drift_score"))
                    if score >= 0.0:
                        self.player_drift_scores[pid] = score
                        changed = True
            except Exception:
                continue
        if changed:
            self.sort_leaderboard()

    def draw_leaderboard(self, ui_surf, font_big, font_medium, font_small, is_host):
        if not self.sorted:
            self.sort_leaderboard()
            self.sorted = True
        # print(self.race_time)
        result = {}

        overlay = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
        overlay.fill((10, 10, 20, 210))
        ui_surf.blit(overlay, (0, 0))

        title = font_big.render("DRIFT RESULTS", True, (255, 220, 80))
        ui_surf.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, 60))

        col_rank_x = const.WINDOW_WIDTH // 2 - 260
        col_name_x = col_rank_x + 70
        col_car_x = col_name_x + 170
        col_score_x = col_car_x + 140
        col_avg_x = col_score_x + 140
        header_y = 120

        for label, lx in [
            ("Rank", col_rank_x),
            ("Player", col_name_x),
            ("Car", col_car_x),
            ("Drift Score", col_score_x),
            ("Average", col_avg_x),
        ]:
            hdr = font_medium.render(label, True, const.GREY_200)
            ui_surf.blit(hdr, (lx, header_y))

        row_y = header_y + 40
        for rank, ps in enumerate(self.leaderboard, start=1):
            color = (255, 215, 0) if rank == 1 else (200, 200, 200) if rank == 2 else (180, 140, 100) if rank == 3 else const.WHITE_240
            rank_s = font_medium.render(f"#{rank}", True, color)
            name_s = font_medium.render(ps.name[:16], True, const.WHITE_240)
            car_s = font_medium.render(ps.car_type, True, const.GREY_200)
            score = int(self.player_drift_scores.get(ps.player_id, 0.0))
            score_s = font_medium.render(str(score), True, (255, 220, 80))
            avg = score / (ps.finish_time if ps.finish_time else 1)
            avg_s = font_medium.render(f"{avg:.1f}/s", True, (255, 220, 80))

            ui_surf.blit(rank_s, (col_rank_x, row_y))
            ui_surf.blit(name_s, (col_name_x, row_y))
            ui_surf.blit(car_s, (col_car_x, row_y))
            ui_surf.blit(score_s, (col_score_x, row_y))
            ui_surf.blit(avg_s, (col_avg_x, row_y))
            row_y += 36

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

    def _draw_race_hud(self, ui_surf, font_medium, font_small, show_timers=True):
        self._draw_drift_angle_hud(ui_surf, font_medium, font_small)

        if show_timers:
            remaining = max(0.0, self.max_time - self.race_time)
            mins = int(remaining) // 60
            secs = remaining - mins * 60
            timer_str = f"{mins}:{secs:05.2f}"
            timer_surf = font_medium.render(timer_str, True, const.WHITE_240)
            ui_surf.blit(timer_surf, (const.WINDOW_WIDTH // 2 - timer_surf.get_width() // 2,
                                      const.TOP_LINE_Y + 78))

    def draw_hud(self, ui_surf, cam, font_big, font_medium, font_small, show_timers=True, show_countdown=True):
        if self.phase == self.PHASE_COUNTDOWN and show_countdown:
            self._draw_countdown(ui_surf, font_big)
        elif self.phase == self.PHASE_RACING:
            self._draw_race_hud(ui_surf, font_medium, font_small, show_timers=show_timers)
        elif self.phase == self.PHASE_COOLDOWN:
            self._draw_race_hud(ui_surf, font_medium, font_small, show_timers=show_timers)
            self._draw_cooldown_banner(ui_surf, font_big)

    def _draw_drift_angle_hud(self, ui_surf, font_medium, font_small):
        max_angle = 90.0
        shown_angle = self.current_drift_angle_deg if self._real_drift_active else 0.0
        angle = max(-max_angle, min(max_angle, shown_angle))
        ratio = (angle + max_angle) / (max_angle * 2.0)

        bar_w = min(520, const.WINDOW_WIDTH - 120)
        bar_h = 24
        bar_x = const.WINDOW_WIDTH // 2 - bar_w // 2
        bar_y = const.TOP_LINE_Y + 8
        bar_rect = pygame.Rect(bar_x, bar_y, bar_w, bar_h)

        bg = pygame.Surface((bar_w, bar_h), pygame.SRCALPHA)
        bg.fill((18, 20, 28, 210))
        ui_surf.blit(bg, bar_rect.topleft)

        center_x = bar_rect.centerx
        pygame.draw.rect(ui_surf, (235, 235, 235), bar_rect, 2, border_radius=12)
        pygame.draw.line(ui_surf, (120, 120, 128), (center_x, bar_y + 3), (center_x, bar_y + bar_h - 3), 2)

        fill_color = (80, 220, 140) if abs(angle) < 25.0 else (255, 205, 90) if abs(angle) < 50.0 else (255, 120, 90)
        slider_x = bar_x + int(ratio * bar_w)
        slider_x = max(bar_x + 10, min(bar_x + bar_w - 10, slider_x))
        slider_rect = pygame.Rect(0, 0, 14, bar_h + 10)
        slider_rect.center = (slider_x, bar_rect.centery)
        pygame.draw.rect(ui_surf, fill_color, slider_rect, border_radius=7)
        pygame.draw.rect(ui_surf, (255, 255, 255), slider_rect, 2, border_radius=7)

        left_label = font_small.render(f"-{int(max_angle)}", True, const.GREY_200)
        right_label = font_small.render(f"+{int(max_angle)}", True, const.GREY_200)
        ui_surf.blit(left_label, (bar_x, bar_y - left_label.get_height() - 2))
        ui_surf.blit(right_label, (bar_x + bar_w - right_label.get_width(), bar_y - right_label.get_height() - 2))

        label_y = bar_y + bar_h + 8
        angle_label = font_medium.render(f"{shown_angle:+.1f}°", True, const.WHITE_240)
        score_label = font_medium.render(f"{int(self.drift_score)}", True, (255, 220, 80))
        combo_label = font_small.render(f"+{int(self.local_drift_score)}", True, (120, 220, 255))
        mult_label = font_medium.render(f"x{self.current_drift_multiplier:.1f}", True, (255, 140, 60))
        gap = 10
        total_w = angle_label.get_width() + gap + score_label.get_width() + gap + mult_label.get_width()
        cx = const.WINDOW_WIDTH // 2 - total_w // 2
        ui_surf.blit(angle_label, (cx, label_y))
        cx += angle_label.get_width() + gap
        ui_surf.blit(score_label, (cx, label_y))
        ui_surf.blit(combo_label, (cx, label_y + score_label.get_height()))
        cx += score_label.get_width() + gap
        ui_surf.blit(mult_label, (cx, label_y))
