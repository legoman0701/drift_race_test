import json
import math
from dataclasses import dataclass
from typing import List, Optional

import pygame

import drift.config.const as const
from drift.tools.paths import asset_path


def _angle_delta(a: float, b: float) -> float:
    return ((a - b + math.pi) % (2.0 * math.pi)) - math.pi


@dataclass
class TutorialStep:
    zone: pygame.Rect
    actions: List[str]
    prompt: str
    min_hold_s: float
    heading_delta_min: float
    brake_speed_drop: float
    accelerate_speed_gain: float


@dataclass
class TutorialFrameState:
    target_time_scale: float = 1.0
    force_ai_drive: bool = False
    prompt: str = ""
    progress: float = 0.0
    active: bool = False


class TutorialController:
    PHASE_IDLE = "idle"
    PHASE_START_QTE = "start_qte"
    PHASE_AI_DRIVE = "ai_drive"
    PHASE_SLOWMO = "slowmo"
    PHASE_RECOVER = "recover"
    PHASE_WAIT_ZONE = "wait_zone"
    PHASE_DONE = "done"
    START_QTE_PROMPT = "Hold Accelerate"
    START_QTE_HOLD_S = 1.0
    POST_QTE_USER_CONTROL_S = float(getattr(const, "TUTORIAL_POST_QTE_USER_CONTROL_S", 2.0))

    def __init__(self, steps: List[TutorialStep]):
        self.steps = steps
        self.phase = self.PHASE_IDLE if not steps else self.PHASE_START_QTE
        self.step_index = 0
        self._hold_s = 0.0
        self._dt_real = 1.0 / 60.0
        self._entered_heading = 0.0
        self._entered_speed = 0.0
        self._handoff_done = False
        self._reentry_required = None
        self._post_qte_user_control_s = 0.0

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
        if self.step_index >= len(self.steps):
            self.phase = self.PHASE_DONE
        else:
            self.phase = self.PHASE_RECOVER
            self._reentry_required = False

    def _can_enter_current_zone(self, in_zone: bool) -> bool:
        # Allow immediate activation while the player keeps holding controls.
        return bool(in_zone)

    def _start_step_context(self, car) -> None:
        self._hold_s = 0.0
        self._entered_heading = car.angle
        self._entered_speed = math.hypot(car.vx, car.vy)

    def on_rewind(self, car) -> None:
        if not self.has_steps or self.is_done:
            return
        self._start_step_context(car)
        self.phase = self.PHASE_SLOWMO

    def update(self, dt_real: float, current_time_scale: float, car, controls: dict) -> TutorialFrameState:
        out = TutorialFrameState()
        self._dt_real = max(0.0, dt_real)
        if self._post_qte_user_control_s > 0.0:
            self._post_qte_user_control_s = max(0.0, self._post_qte_user_control_s - self._dt_real)

        if self.phase == self.PHASE_START_QTE:
            th = float(controls.get("th", 0.0))
            out.active = True
            out.prompt = self.START_QTE_PROMPT
            out.target_time_scale = max(const.TUTORIAL_MIN_TIME_SCALE, const.TUTORIAL_ACCEL_ONLY_MIN_TIME_SCALE)
            if th >= const.TUTORIAL_ACCEL_INPUT_THRESHOLD:
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

        in_zone = step.zone.collidepoint(car.x, car.y)
        zone_ready = self._can_enter_current_zone(in_zone)

        # Entering a tutorial step zone should override transitional phases
        # immediately so prompts cannot be skipped.
        if zone_ready and self.phase in (self.PHASE_AI_DRIVE, self.PHASE_RECOVER, self.PHASE_WAIT_ZONE):
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
            requires_turn = ("turn_left" in step.actions) or ("turn_right" in step.actions)
            requires_brake = "brake" in step.actions
            requires_accelerate = "accelerate" in step.actions
            if requires_turn and not requires_brake:
                out.target_time_scale = max(const.TUTORIAL_MIN_TIME_SCALE, const.TUTORIAL_TURN_ONLY_MIN_TIME_SCALE)
            elif requires_accelerate and not requires_brake:
                out.target_time_scale = max(const.TUTORIAL_MIN_TIME_SCALE, const.TUTORIAL_ACCEL_ONLY_MIN_TIME_SCALE)
            else:
                out.target_time_scale = const.TUTORIAL_MIN_TIME_SCALE
            done = self._evaluate_step(step, car, controls)
            out.progress = min(1.0, self._hold_s / max(0.001, step.min_hold_s))
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
            out.progress = min(1.0, self._hold_s / max(0.001, step.min_hold_s))

        # Player input is allowed during active QTE windows and for a short
        # grace period right after a QTE completes.
        qte_active = self.phase in (self.PHASE_START_QTE, self.PHASE_SLOWMO)
        in_post_qte_grace = self._post_qte_user_control_s > 0.0
        out.force_ai_drive = not (qte_active or in_post_qte_grace)

        return out

    def _evaluate_step(self, step: TutorialStep, car, controls: dict) -> bool:
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

        return self._hold_s >= step.min_hold_s


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
            zone = pygame.Rect(
                int(zone_obj.get("x", 0)),
                int(zone_obj.get("y", 0)),
                max(1, int(zone_obj.get("width", 1))),
                max(1, int(zone_obj.get("height", 1))),
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
                zone=zone,
                actions=actions,
                prompt=prompt,
                min_hold_s=float(entry.get("min_hold_s", const.TUTORIAL_ACTION_MIN_HOLD_S)),
                heading_delta_min=float(entry.get("heading_delta_min", const.TUTORIAL_HEADING_DELTA_MIN_RAD)),
                brake_speed_drop=float(entry.get("brake_speed_drop", const.TUTORIAL_BRAKE_SPEED_DROP_MIN)),
                accelerate_speed_gain=float(entry.get("accelerate_speed_gain", const.TUTORIAL_ACCEL_SPEED_GAIN_MIN)),
            )
        )
    return steps