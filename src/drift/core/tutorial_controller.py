import json
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

import drift.config.const as const
from drift.tools.paths import asset_path


def _angle_delta(a: float, b: float) -> float:
    return ((a - b + math.pi) % (2.0 * math.pi)) - math.pi


@dataclass
class TutorialStep:
    line_start: Tuple[float, float]
    line_end: Tuple[float, float]
    actions: List[str]
    prompt: str
    min_hold_s: float
    heading_delta_min: float
    brake_speed_drop: float
    accelerate_speed_gain: float

    @property
    def target_point(self) -> Tuple[float, float]:
        return (
            (float(self.line_start[0]) + float(self.line_end[0])) * 0.5,
            (float(self.line_start[1]) + float(self.line_end[1])) * 0.5,
        )


@dataclass
class TutorialFrameState:
    target_time_scale: float = 1.0
    force_ai_drive: bool = False
    prompt: str = ""
    progress: float = 0.0
    active: bool = False
    hint_image: str = ""


class TutorialController:
    PHASE_IDLE = "idle"
    PHASE_START_QTE = "start_qte"
    PHASE_AI_DRIVE = "ai_drive"
    PHASE_SLOWMO = "slowmo"
    PHASE_RECOVER = "recover"
    PHASE_WAIT_ZONE = "wait_zone"
    PHASE_DONE = "done"
    START_QTE_PROMPT = "Accelerate to Start"
    START_QTE_HOLD_S = 1.0
    POST_QTE_USER_CONTROL_S = float(getattr(const, "TUTORIAL_POST_QTE_USER_CONTROL_S", 2.0))
    SAFE_MIN_TIME_SCALE = max(0.0, float(getattr(const, "TUTORIAL_MIN_TIME_SCALE", 0.0)))
    LINE_TOUCH_RADIUS = max(12.0, float(getattr(const, "CAR_WID", 20.0)) * 0.75)

    def __init__(self, steps: List[TutorialStep], allow_ai_takeover_between_qte: bool = True, enable_qte: bool = True, start_qte_intro_text: str = "", auto_fill_actions: bool = False):
        self.steps = steps
        self.phase = self.PHASE_IDLE if not steps else self.PHASE_START_QTE
        self.allow_ai_takeover_between_qte = bool(allow_ai_takeover_between_qte)
        self.enable_qte = bool(enable_qte)
        self.start_qte_intro_text = str(start_qte_intro_text or "").strip()
        self.auto_fill_actions = bool(auto_fill_actions)
        self.step_index = 0
        self._hold_s = 0.0
        self._dt_real = 1.0 / 60.0
        self._entered_heading = 0.0
        self._entered_speed = 0.0
        self._handoff_done = False
        self._reentry_required = None
        self._post_qte_user_control_s = 0.0
        # Start QTE must be a fresh accelerate hold: require a release first.
        self._start_qte_released = False
        # One-shot activation per step: once touched, a zone is consumed.
        self._zone_consumed_step = -1
        self._prev_car_pos: Optional[Tuple[float, float]] = None

    @property
    def has_steps(self) -> bool:
        return len(self.steps) > 0

    @property
    def is_done(self) -> bool:
        return self.phase == self.PHASE_DONE

    def _current_step(self) -> Optional[TutorialStep]:
        if 0 <= self.step_index < len(self.steps):
            return self.steps[self.step_index]
        return None

    def _advance_step(self, car) -> None:
        self.step_index += 1
        self._hold_s = 0.0
        self._post_qte_user_control_s = self.POST_QTE_USER_CONTROL_S
        self._entered_heading = car.angle
        self._entered_speed = math.hypot(car.vx, car.vy)
        self._zone_consumed_step = -1
        if self.step_index >= len(self.steps):
            self.phase = self.PHASE_DONE
        else:
            self.phase = self.PHASE_RECOVER
            self._reentry_required = False

    def _can_enter_current_zone(self, in_zone: bool) -> bool:
        # Activation lines are one-shot per step.
        if self._zone_consumed_step == self.step_index:
            return False
        return bool(in_zone)

    @staticmethod
    def _point_to_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
        abx = bx - ax
        aby = by - ay
        apx = px - ax
        apy = py - ay
        denom = (abx * abx) + (aby * aby)
        if denom <= 1e-9:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
        qx = ax + t * abx
        qy = ay + t * aby
        return math.hypot(px - qx, py - qy)

    @staticmethod
    def _segments_intersect(a1: Tuple[float, float], a2: Tuple[float, float], b1: Tuple[float, float], b2: Tuple[float, float]) -> bool:
        def _orient(p, q, r):
            return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

        def _on_seg(p, q, r):
            return (
                min(p[0], r[0]) - 1e-6 <= q[0] <= max(p[0], r[0]) + 1e-6
                and min(p[1], r[1]) - 1e-6 <= q[1] <= max(p[1], r[1]) + 1e-6
            )

        o1 = _orient(a1, a2, b1)
        o2 = _orient(a1, a2, b2)
        o3 = _orient(b1, b2, a1)
        o4 = _orient(b1, b2, a2)

        if (o1 > 0) != (o2 > 0) and (o3 > 0) != (o4 > 0):
            return True
        if abs(o1) <= 1e-6 and _on_seg(a1, b1, a2):
            return True
        if abs(o2) <= 1e-6 and _on_seg(a1, b2, a2):
            return True
        if abs(o3) <= 1e-6 and _on_seg(b1, a1, b2):
            return True
        if abs(o4) <= 1e-6 and _on_seg(b1, a2, b2):
            return True
        return False

    def _step_line_touched(self, step: TutorialStep, car) -> bool:
        x1, y1 = float(step.line_start[0]), float(step.line_start[1])
        x2, y2 = float(step.line_end[0]), float(step.line_end[1])
        cx, cy = float(car.x), float(car.y)

        if self._point_to_segment_distance(cx, cy, x1, y1, x2, y2) <= self.LINE_TOUCH_RADIUS:
            return True

        if self._prev_car_pos is not None:
            px, py = self._prev_car_pos
            if self._segments_intersect((px, py), (cx, cy), (x1, y1), (x2, y2)):
                return True
        return False

    def _start_step_context(self, car) -> None:
        self._hold_s = 0.0
        self._entered_heading = car.angle
        self._entered_speed = math.hypot(car.vx, car.vy)

    def _hint_image_for_actions(self, actions: List[str]) -> str:
        s = {str(a).strip().lower() for a in (actions or [])}
        has_left = "turn_left" in s
        has_right = "turn_right" in s
        has_brake = "brake" in s
        has_acc = "accelerate" in s
        has_straight = any(a in s for a in ("straighten_out", "straighten", "straight"))

        if has_brake and has_right:
            return "SD.png"
        if has_brake and has_left:
            return "SQ.png"
        if has_acc and has_right:
            return "ZD.png"
        if has_acc and has_left:
            return "ZQ.png"
        if has_acc and (has_straight or (not has_left and not has_right)):
            return "Z.png"
        return ""

    def _required_hold_s(self, step: TutorialStep) -> float:
        base = max(0.001, float(step.min_hold_s))
        if self.auto_fill_actions:
            return base * 2.0
        return base

    def on_rewind(self, car) -> None:
        if not self.has_steps or self.is_done:
            return
        self._start_step_context(car)
        self.phase = self.PHASE_SLOWMO

    def get_rewind_snapshot(self) -> dict:
        """Capture minimal controller state to restore tutorial flow after rewind."""
        return {
            "phase": str(self.phase),
            "step_index": int(self.step_index),
            "hold_s": float(self._hold_s),
            "post_qte_user_control_s": float(self._post_qte_user_control_s),
            "start_qte_released": bool(self._start_qte_released),
            "handoff_done": bool(self._handoff_done),
            "reentry_required": self._reentry_required,
            "zone_consumed_step": int(self._zone_consumed_step),
        }

    def apply_rewind_snapshot(self, snapshot: dict, car) -> None:
        """Restore controller state from a rewind snapshot, with safe fallbacks."""
        if not isinstance(snapshot, dict):
            self.on_rewind(car)
            return

        raw_idx = int(snapshot.get("step_index", self.step_index))
        if self.steps:
            raw_idx = max(0, min(len(self.steps) - 1, raw_idx))
        else:
            raw_idx = 0
        self.step_index = raw_idx

        valid_phases = {
            self.PHASE_IDLE,
            self.PHASE_START_QTE,
            self.PHASE_AI_DRIVE,
            self.PHASE_SLOWMO,
            self.PHASE_RECOVER,
            self.PHASE_WAIT_ZONE,
            self.PHASE_DONE,
        }
        phase = str(snapshot.get("phase", self.phase))
        self.phase = phase if phase in valid_phases else self.PHASE_SLOWMO

        self._hold_s = max(0.0, float(snapshot.get("hold_s", 0.0)))
        self._post_qte_user_control_s = max(0.0, float(snapshot.get("post_qte_user_control_s", 0.0)))
        self._start_qte_released = bool(snapshot.get("start_qte_released", self._start_qte_released))
        self._handoff_done = bool(snapshot.get("handoff_done", self._handoff_done))
        self._reentry_required = snapshot.get("reentry_required", self._reentry_required)
        self._zone_consumed_step = int(snapshot.get("zone_consumed_step", self._zone_consumed_step))

        # Keep motion references coherent after teleporting the car during rewind.
        self._entered_heading = car.angle
        self._entered_speed = math.hypot(car.vx, car.vy)

    def update(self, dt_real: float, current_time_scale: float, car, controls: dict) -> TutorialFrameState:
        out = TutorialFrameState()
        self._dt_real = max(0.0, dt_real)
        current_pos = (float(car.x), float(car.y))

        # Tutorial profile without QTE: keep the initial start prompt, then
        # progress steps instantly on line touch with no prompt/slowmo overlays.
        if not self.enable_qte and self.phase != self.PHASE_START_QTE:
            step = self._current_step()
            if step is None:
                self.phase = self.PHASE_DONE if self.has_steps else self.PHASE_IDLE
                out.target_time_scale = 1.0
                out.active = False
                out.prompt = ""
                out.force_ai_drive = self.allow_ai_takeover_between_qte
                self._prev_car_pos = current_pos
                return out

            if self._step_line_touched(step, car):
                self.step_index += 1
                if self.step_index >= len(self.steps):
                    self.phase = self.PHASE_DONE
                else:
                    self.phase = self.PHASE_AI_DRIVE

            out.target_time_scale = 1.0
            out.active = False
            out.prompt = ""
            out.progress = 0.0
            out.force_ai_drive = self.allow_ai_takeover_between_qte
            self._prev_car_pos = current_pos
            return out

        if self._post_qte_user_control_s > 0.0:
            self._post_qte_user_control_s = max(0.0, self._post_qte_user_control_s - self._dt_real)

        if self.phase == self.PHASE_START_QTE:
            th = float(controls.get("th", 0.0))
            out.active = True
            out.hint_image = "Z.png"
            if self.start_qte_intro_text:
                out.prompt = f"{self.start_qte_intro_text}\n{self.START_QTE_PROMPT}"
            else:
                out.prompt = self.START_QTE_PROMPT
            out.target_time_scale = max(self.SAFE_MIN_TIME_SCALE, const.TUTORIAL_ACCEL_ONLY_MIN_TIME_SCALE)

            # Prevent auto-skip when accelerate is already held on tutorial start:
            # first observe a release, then require a fresh hold.
            release_threshold = const.TUTORIAL_ACCEL_INPUT_THRESHOLD * 0.5
            if not self._start_qte_released:
                if th <= release_threshold:
                    self._start_qte_released = True
                    self._hold_s = 0.0
            elif th >= const.TUTORIAL_ACCEL_INPUT_THRESHOLD:
                self._hold_s += self._dt_real
            else:
                self._hold_s = max(0.0, self._hold_s - self._dt_real * 0.75)
            out.progress = min(1.0, self._hold_s / max(0.001, self.START_QTE_HOLD_S))
            if self._hold_s >= self.START_QTE_HOLD_S:
                self._hold_s = 0.0
                self._post_qte_user_control_s = self.POST_QTE_USER_CONTROL_S
                self.phase = self.PHASE_AI_DRIVE

        step = self._current_step()

        if step is None:
            out.target_time_scale = 1.0
            out.active = False
            self.phase = self.PHASE_DONE if self.has_steps else self.PHASE_IDLE
            return out

        in_zone = self._step_line_touched(step, car)
        zone_ready = self._can_enter_current_zone(in_zone)

        # Entering a tutorial step zone should override transitional phases
        # immediately so prompts cannot be skipped.
        if zone_ready and self.phase in (self.PHASE_AI_DRIVE, self.PHASE_RECOVER, self.PHASE_WAIT_ZONE):
            self._zone_consumed_step = self.step_index
            self.phase = self.PHASE_SLOWMO
            self._post_qte_user_control_s = 0.0
            self._start_step_context(car)

        if self.phase == self.PHASE_AI_DRIVE:
            out.target_time_scale = 1.0
            out.active = False
            if zone_ready:
                self._handoff_done = True
                self._reentry_required = False

        if self.phase == self.PHASE_SLOWMO:
            out.active = True
            out.prompt = step.prompt
            out.hint_image = self._hint_image_for_actions(step.actions)
            requires_turn = ("turn_left" in step.actions) or ("turn_right" in step.actions)
            requires_brake = "brake" in step.actions
            requires_accelerate = "accelerate" in step.actions
            if requires_turn and not requires_brake:
                out.target_time_scale = max(self.SAFE_MIN_TIME_SCALE, const.TUTORIAL_TURN_ONLY_MIN_TIME_SCALE)
            elif requires_accelerate and not requires_brake:
                out.target_time_scale = max(self.SAFE_MIN_TIME_SCALE, const.TUTORIAL_ACCEL_ONLY_MIN_TIME_SCALE)
            else:
                out.target_time_scale = self.SAFE_MIN_TIME_SCALE
            done = self._evaluate_step(step, car, controls)
            out.progress = min(1.0, self._hold_s / self._required_hold_s(step))
            if done:
                self._advance_step(car)

        if self.phase == self.PHASE_RECOVER:
            out.active = False
            out.target_time_scale = 1.0
            if current_time_scale >= 0.98:
                self.phase = self.PHASE_WAIT_ZONE

        if self.phase == self.PHASE_WAIT_ZONE:
            out.active = False
            out.target_time_scale = 1.0
            if zone_ready:
                self._zone_consumed_step = self.step_index
                self.phase = self.PHASE_SLOWMO
                self._post_qte_user_control_s = 0.0
                self._start_step_context(car)
                self._reentry_required = False

        if self.phase == self.PHASE_DONE:
            out.target_time_scale = 1.0
            out.active = False
            out.prompt = ""

        if self.phase == self.PHASE_SLOWMO and out.active:
            # Hold timer is evaluated against real frame time so tutorial difficulty
            # is stable even when simulation time scale changes.
            out.progress = min(1.0, self._hold_s / self._required_hold_s(step))

        # Player input is allowed during active QTE windows and for a short
        # grace period right after a QTE completes, unless tutorial profile
        # disables AI takeover between QTE windows.
        if not self.allow_ai_takeover_between_qte:
            out.force_ai_drive = False
        else:
            qte_active = self.phase in (self.PHASE_START_QTE, self.PHASE_SLOWMO)
            in_post_qte_grace = self._post_qte_user_control_s > 0.0
            out.force_ai_drive = not (qte_active or in_post_qte_grace)

        self._prev_car_pos = current_pos
        return out

    def _evaluate_step(self, step: TutorialStep, car, controls: dict) -> bool:
        required_hold = self._required_hold_s(step)
        if self.auto_fill_actions:
            self._hold_s += self._dt_real
            return self._hold_s >= required_hold

        th = float(controls.get("th", 0.0))
        st = float(controls.get("st", 0.0))
        br = float(controls.get("br", 0.0))

        requires_turn_right = "turn_right" in step.actions
        requires_turn_left = "turn_left" in step.actions
        requires_brake = "brake" in step.actions
        requires_accelerate = "accelerate" in step.actions
        requires_straighten = any(a in step.actions for a in ("straighten_out", "straighten", "straight"))

        # Non-requested controls must stay mostly inactive while holding a step.
        steer_idle_max = const.TUTORIAL_STEER_INPUT_THRESHOLD * 0.35
        accel_idle_max = const.TUTORIAL_ACCEL_INPUT_THRESHOLD * 0.35
        brake_idle_max = const.TUTORIAL_BRAKE_INPUT_THRESHOLD * 0.35
        steer_straight_max = const.TUTORIAL_STEER_INPUT_THRESHOLD * 0.5

        input_ok = True
        # Guard against conflicting step definitions.
        if (requires_turn_right and requires_turn_left) or (requires_straighten and (requires_turn_right or requires_turn_left)):
            input_ok = False

        if requires_turn_right:
            input_ok = input_ok and (st >= const.TUTORIAL_STEER_INPUT_THRESHOLD)
        elif requires_turn_left:
            input_ok = input_ok and (st <= -const.TUTORIAL_STEER_INPUT_THRESHOLD)
        elif requires_straighten:
            # Require near-neutral steering while holding the combo.
            input_ok = input_ok and (abs(st) <= steer_straight_max)
        else:
            input_ok = input_ok and (abs(st) <= steer_idle_max)

        if requires_brake:
            input_ok = input_ok and (br >= const.TUTORIAL_BRAKE_INPUT_THRESHOLD)
        else:
            input_ok = input_ok and (br <= brake_idle_max)

        if requires_accelerate:
            input_ok = input_ok and (th >= const.TUTORIAL_ACCEL_INPUT_THRESHOLD)
        else:
            input_ok = input_ok and (th <= accel_idle_max)

        # Tutorial progression is purely based on holding the requested controls
        # long enough, independent of vehicle motion/heading changes.
        if input_ok:
            self._hold_s += self._dt_real
        else:
            self._hold_s = max(0.0, self._hold_s - self._dt_real * 0.75)

        return self._hold_s >= required_hold


def load_tutorial_steps_for_map(map_num: int) -> List[TutorialStep]:
    steps: List[TutorialStep] = []
    meta_path = asset_path("track", f"map{map_num}", "map_meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        return steps

    raw_tutorial = meta.get("tutorial")
    if not isinstance(raw_tutorial, dict):
        return steps

    raw_steps = raw_tutorial.get("steps") or []
    if not isinstance(raw_steps, list):
        return steps

    for entry in raw_steps:
        if not isinstance(entry, dict):
            continue
        zone_obj = entry.get("zone") or {}
        try:
            # Legacy line format: x,y is line start ; end is x+width, y+height.
            sx = float(zone_obj.get("x", 0))
            sy = float(zone_obj.get("y", 0))
            dx = float(zone_obj.get("width", 0))
            dy = float(zone_obj.get("height", 0))
            line_start = (
                sx,
                sy,
            )
            line_end = (
                sx + dx,
                sy + dy,
            )
        except Exception:
            continue

        actions = entry.get("actions") or []
        if isinstance(actions, str):
            actions = [actions]
        actions = [str(a).strip().lower() for a in actions if str(a).strip()]
        if not actions:
            continue

        prompt = str(entry.get("prompt") or "")
        if not prompt:
            pretty = " + ".join(a.replace("_", " ").title() for a in actions)
            prompt = f"Do: {pretty}"

        steps.append(
            TutorialStep(
                line_start=line_start,
                line_end=line_end,
                actions=actions,
                prompt=prompt,
                min_hold_s=float(entry.get("min_hold_s", const.TUTORIAL_ACTION_MIN_HOLD_S)),
                heading_delta_min=float(entry.get("heading_delta_min", const.TUTORIAL_HEADING_DELTA_MIN_RAD)),
                brake_speed_drop=float(entry.get("brake_speed_drop", const.TUTORIAL_BRAKE_SPEED_DROP_MIN)),
                accelerate_speed_gain=float(entry.get("accelerate_speed_gain", const.TUTORIAL_ACCEL_SPEED_GAIN_MIN)),
            )
        )
    return steps