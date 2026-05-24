#!/usr/bin/env python3
"""
Tutorial zone editor for drift tutorial authoring.

Usage:
    python -m drift.tools.tutorial_editor --map 3

Controls:
    Left Mouse Drag: create or edit current step line
    N: add new step
    TAB / SHIFT+TAB: next/previous step
    DELETE/BACKSPACE: delete current step
    E: toggle end-zone edit mode
    A: cycle action preset
    P: cycle prompt preset
    S: save map_meta.json
    L: reload map_meta.json
    ESC: quit
"""

import argparse
import json
import os
import pygame

import drift.config.const as const
from drift.tools.paths import asset_path, get_track_base_image_path


_ACTION_PRESETS = [
    (["accelerate"], "Accelerate"),
    (["straighten_out", "accelerate"], "Straighten Out + Accelerate"),
    (["turn_right"], "Turn Right"),
    (["turn_left"], "Turn Left"),
    (["brake"], "Brake"),
    (["turn_right", "accelerate"], "Turn Right + Accelerate"),
    (["turn_left", "accelerate"], "Turn Left + Accelerate"),
    (["turn_right", "brake"], "Turn Right + Brake"),
    (["turn_left", "brake"], "Turn Left + Brake"),
]


class TutorialEditor:
    def __init__(self, map_num: int):
        pygame.init()
        self.map_num = int(map_num)
        self.screen = pygame.display.set_mode((1400, 900))
        pygame.display.set_caption(f"Tutorial Editor - map{self.map_num}")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 18)
        self.font_small = pygame.font.SysFont("Arial", 14)

        self.map_image = self._load_map_image()
        self.camera_x = self.map_image.get_width() / 2.0
        self.camera_y = self.map_image.get_height() / 2.0
        self.zoom = 0.5

        self.steps = []
        self.end_zone = None
        self.edit_end_zone = False
        self.selected = 0
        self.dragging = False
        self.drag_anchor = (0, 0)
        self.running = True

        self._load()

    def _meta_path(self) -> str:
        return asset_path("track", f"map{self.map_num}", "map_meta.json")

    def _load_map_image(self):
        try:
            return pygame.image.load(get_track_base_image_path(f"map{self.map_num}")).convert()
        except Exception:
            surf = pygame.Surface((2000, 1500))
            surf.fill((30, 30, 30))
            return surf

    def _screen_to_world(self, sx, sy):
        wx = (sx - self.screen.get_width() / 2) / self.zoom + self.camera_x
        wy = (sy - self.screen.get_height() / 2) / self.zoom + self.camera_y
        return int(wx), int(wy)

    def _world_to_screen(self, wx, wy):
        sx = int((wx - self.camera_x) * self.zoom + self.screen.get_width() / 2)
        sy = int((wy - self.camera_y) * self.zoom + self.screen.get_height() / 2)
        return sx, sy

    def _load(self):
        self.steps = []
        self.end_zone = None
        path = self._meta_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            tutorial = meta.get("tutorial", {}) if isinstance(meta, dict) else {}
            raw_steps = tutorial.get("steps", []) if isinstance(tutorial, dict) else []
            for st in raw_steps:
                if not isinstance(st, dict):
                    continue
                zone = st.get("zone", {})
                self.steps.append({
                    "zone": {
                        "x": int(zone.get("x", 0)),
                        "y": int(zone.get("y", 0)),
                        # Legacy line mode: width/height are line deltas from origin.
                        "width": int(zone.get("width", 160)),
                        "height": int(zone.get("height", 0)),
                    },
                    "actions": st.get("actions", ["turn_right"]),
                    "prompt": st.get("prompt", "Turn Right"),
                    "min_hold_s": float(st.get("min_hold_s", const.TUTORIAL_ACTION_MIN_HOLD_S)),
                    "heading_delta_min": float(st.get("heading_delta_min", const.TUTORIAL_HEADING_DELTA_MIN_RAD)),
                    "brake_speed_drop": float(st.get("brake_speed_drop", const.TUTORIAL_BRAKE_SPEED_DROP_MIN)),
                })

            raw_end = tutorial.get("end_zone") if isinstance(tutorial, dict) else None
            if isinstance(raw_end, dict):
                self.end_zone = {
                    "x": int(raw_end.get("x", 0)),
                    "y": int(raw_end.get("y", 0)),
                    "width": max(1, int(raw_end.get("width", 10))),
                    "height": max(1, int(raw_end.get("height", 10))),
                }
        except Exception:
            self.steps = []
            self.end_zone = None

        if not self.steps:
            actions, prompt = _ACTION_PRESETS[0]
            self.steps.append({
                "zone": {"x": 100, "y": 100, "width": 160, "height": 0},
                "actions": list(actions),
                "prompt": prompt,
                "min_hold_s": const.TUTORIAL_ACTION_MIN_HOLD_S,
                "heading_delta_min": const.TUTORIAL_HEADING_DELTA_MIN_RAD,
                "brake_speed_drop": const.TUTORIAL_BRAKE_SPEED_DROP_MIN,
            })
        self.selected = min(self.selected, len(self.steps) - 1)
        self.edit_end_zone = False

    def _save(self):
        path = self._meta_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        meta = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
            except Exception:
                meta = {}

        tutorial = {"steps": self.steps}
        if isinstance(self.end_zone, dict):
            tutorial["end_zone"] = {
                "x": int(self.end_zone.get("x", 0)),
                "y": int(self.end_zone.get("y", 0)),
                "width": max(1, int(self.end_zone.get("width", 1))),
                "height": max(1, int(self.end_zone.get("height", 1))),
            }
        meta["tutorial"] = tutorial
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self._format_json(meta))

    def _format_json(self, data, indent=0):
        """Format JSON with compact arrays/objects (same style as collision editor)."""
        lines = []
        indent_str = "    " * indent

        if isinstance(data, dict):
            lines.append("{")
            items = list(data.items())
            for i, (key, value) in enumerate(items):
                comma = "," if i < len(items) - 1 else ""

                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], dict):
                    lines.append(f'{indent_str}    "{key}": [')
                    for j, item in enumerate(value):
                        item_comma = "," if j < len(value) - 1 else ""
                        lines.append(f'{indent_str}        {json.dumps(item)}{item_comma}')
                    lines.append(f'{indent_str}    ]{comma}')
                elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], list):
                    if len(value[0]) > 0 and isinstance(value[0][0], list):
                        lines.append(f'{indent_str}    "{key}": [')
                        for j, shape in enumerate(value):
                            shape_comma = "," if j < len(value) - 1 else ""
                            lines.append(f'{indent_str}        [')
                            for k, vertex in enumerate(shape):
                                vertex_comma = "," if k < len(shape) - 1 else ""
                                lines.append(f'{indent_str}            {json.dumps(vertex)}{vertex_comma}')
                            lines.append(f'{indent_str}        ]{shape_comma}')
                        lines.append(f'{indent_str}    ]{comma}')
                    else:
                        lines.append(f'{indent_str}    "{key}": [')
                        for j, item in enumerate(value):
                            item_comma = "," if j < len(value) - 1 else ""
                            lines.append(f'{indent_str}        {json.dumps(item)}{item_comma}')
                        lines.append(f'{indent_str}    ]{comma}')
                elif isinstance(value, (dict, list)):
                    formatted_value = self._format_json(value, indent + 1)
                    lines.append(f'{indent_str}    "{key}": {formatted_value}{comma}')
                else:
                    lines.append(f'{indent_str}    "{key}": {json.dumps(value)}{comma}')
            lines.append(f'{indent_str}}}')
            return "\n".join(lines)

        elif isinstance(data, list):
            if len(data) == 0:
                return "[]"
            lines.append("[")
            for i, item in enumerate(data):
                comma = "," if i < len(data) - 1 else ""
                if isinstance(item, (dict, list)):
                    formatted_item = self._format_json(item, indent + 1)
                    indented_item = "\n".join(
                        f'{indent_str}    {line}' if j > 0 else line
                        for j, line in enumerate(formatted_item.split("\n"))
                    )
                    lines.append(f'{indent_str}    {indented_item}{comma}')
                else:
                    lines.append(f'{indent_str}    {json.dumps(item)}{comma}')
            lines.append(f'{indent_str}]')
            return "\n".join(lines)

        else:
            return json.dumps(data)

    def _cycle_action(self):
        if not self.steps:
            return
        cur = self.steps[self.selected]
        cur_actions = tuple(cur.get("actions", []))
        idx = 0
        for i, (actions, _prompt) in enumerate(_ACTION_PRESETS):
            if tuple(actions) == cur_actions:
                idx = i
                break
        next_actions, next_prompt = _ACTION_PRESETS[(idx + 1) % len(_ACTION_PRESETS)]
        cur["actions"] = list(next_actions)
        cur["prompt"] = next_prompt

    def _cycle_prompt(self):
        if not self.steps:
            return
        cur = self.steps[self.selected]
        prompt = str(cur.get("prompt", ""))
        presets = [p for _, p in _ACTION_PRESETS]
        try:
            idx = presets.index(prompt)
        except ValueError:
            idx = -1
        cur["prompt"] = presets[(idx + 1) % len(presets)]

    def _set_zone_from_drag(self, world_now):
        if self.edit_end_zone:
            self._set_end_zone_from_drag(world_now)
        else:
            self._set_step_line_from_drag(world_now)

    def _set_end_zone_from_drag(self, world_now):
        ax, ay = self.drag_anchor
        bx, by = world_now
        x0, y0 = min(ax, bx), min(ay, by)
        x1, y1 = max(ax, bx), max(ay, by)
        zone = {
            "x": int(x0),
            "y": int(y0),
            "width": max(1, int(x1 - x0)),
            "height": max(1, int(y1 - y0)),
        }
        self.end_zone = zone

    def _set_step_line_from_drag(self, world_now):
        ax, ay = self.drag_anchor
        bx, by = world_now
        zone = {
            "x": int(ax),
            "y": int(ay),
            # Legacy line mode: width/height store line delta from origin.
            "width": int(bx - ax),
            "height": int(by - ay),
        }
        if not self.steps:
            return
        self.steps[self.selected]["zone"] = zone

    def _draw(self):
        self.screen.fill((18, 18, 20))

        img_w = int(self.map_image.get_width() * self.zoom)
        img_h = int(self.map_image.get_height() * self.zoom)
        map_scaled = pygame.transform.smoothscale(self.map_image, (max(1, img_w), max(1, img_h)))
        top_left = self._world_to_screen(0, 0)
        self.screen.blit(map_scaled, top_left)

        for i, step in enumerate(self.steps):
            zone = step.get("zone", {})
            x1, y1 = int(zone.get("x", 0)), int(zone.get("y", 0))
            x2, y2 = x1 + int(zone.get("width", 0)), y1 + int(zone.get("height", 0))
            sx1, sy1 = self._world_to_screen(x1, y1)
            sx2, sy2 = self._world_to_screen(x2, y2)
            color = (80, 220, 120) if i == self.selected else (220, 150, 70)
            pygame.draw.line(self.screen, color, (sx1, sy1), (sx2, sy2), 3)
            pygame.draw.circle(self.screen, color, (sx1, sy1), 4)
            pygame.draw.circle(self.screen, color, (sx2, sy2), 4)
            lx = (sx1 + sx2) // 2
            ly = (sy1 + sy2) // 2
            label = self.font_small.render(f"{i+1}: {step.get('prompt', '')}", True, color)
            self.screen.blit(label, (lx + 6, ly - 10))

        if isinstance(self.end_zone, dict):
            ez = self.end_zone
            ex, ey = int(ez.get("x", 0)), int(ez.get("y", 0))
            ew, eh = int(ez.get("width", 1)), int(ez.get("height", 1))
            esx, esy = self._world_to_screen(ex, ey)
            esw = max(1, int(ew * self.zoom))
            esh = max(1, int(eh * self.zoom))
            erect = pygame.Rect(esx, esy, esw, esh)
            ecolor = (120, 220, 255) if self.edit_end_zone else (90, 170, 220)
            pygame.draw.rect(self.screen, ecolor, erect, 2)
            elabel = self.font_small.render("END ZONE", True, ecolor)
            self.screen.blit(elabel, (esx + 4, esy + 4))

        mode = "END ZONE" if self.edit_end_zone else "STEP"
        status = "LMB drag: line | E end-zone mode | N new | TAB next | A action | P prompt | S save | L load | Del delete/clear | ESC quit"
        info = self.font.render(status, True, (230, 230, 240))
        self.screen.blit(info, (12, 8))

        mode_s = self.font.render(f"edit mode: {mode}", True, (180, 220, 255))
        self.screen.blit(mode_s, (12, 32))

        if self.steps:
            step = self.steps[self.selected]
            detail = f"step {self.selected + 1}/{len(self.steps)} actions={step.get('actions')} hold={step.get('min_hold_s', 0):.2f}s"
            detail_s = self.font.render(detail, True, (180, 210, 255))
            self.screen.blit(detail_s, (12, 56))

        pygame.display.flip()

    def run(self):
        while self.running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        self.running = False
                    elif ev.key == pygame.K_s:
                        self._save()
                    elif ev.key == pygame.K_l:
                        self._load()
                    elif ev.key == pygame.K_e:
                        self.edit_end_zone = not self.edit_end_zone
                        if self.edit_end_zone and self.end_zone is None:
                            if self.steps:
                                z = self.steps[self.selected].get("zone", {})
                                sx = int(z.get("x", 100))
                                sy = int(z.get("y", 100))
                                ex = sx + int(z.get("width", 160))
                                ey = sy + int(z.get("height", 0))
                                x0, y0 = min(sx, ex), min(sy, ey)
                                x1, y1 = max(sx, ex), max(sy, ey)
                                self.end_zone = {
                                    "x": x0,
                                    "y": y0,
                                    "width": max(1, x1 - x0),
                                    "height": max(1, y1 - y0),
                                }
                            else:
                                self.end_zone = {"x": 100, "y": 100, "width": 160, "height": 100}
                    elif ev.key == pygame.K_n:
                        actions, prompt = _ACTION_PRESETS[0]
                        self.steps.append({
                            "zone": {"x": 100, "y": 100, "width": 160, "height": 0},
                            "actions": list(actions),
                            "prompt": prompt,
                            "min_hold_s": const.TUTORIAL_ACTION_MIN_HOLD_S,
                            "heading_delta_min": const.TUTORIAL_HEADING_DELTA_MIN_RAD,
                            "brake_speed_drop": const.TUTORIAL_BRAKE_SPEED_DROP_MIN,
                        })
                        self.selected = len(self.steps) - 1
                    elif ev.key == pygame.K_TAB:
                        if self.edit_end_zone:
                            continue
                        if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                            self.selected = (self.selected - 1) % len(self.steps)
                        else:
                            self.selected = (self.selected + 1) % len(self.steps)
                    elif ev.key in (pygame.K_DELETE, pygame.K_BACKSPACE):
                        if self.edit_end_zone:
                            self.end_zone = None
                            continue
                        if len(self.steps) > 1:
                            self.steps.pop(self.selected)
                            self.selected = max(0, min(self.selected, len(self.steps) - 1))
                    elif ev.key == pygame.K_a:
                        if self.edit_end_zone:
                            continue
                        self._cycle_action()
                    elif ev.key == pygame.K_p:
                        if self.edit_end_zone:
                            continue
                        self._cycle_prompt()

                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    self.dragging = True
                    self.drag_anchor = self._screen_to_world(*ev.pos)
                    self._set_zone_from_drag(self.drag_anchor)
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    if self.dragging:
                        self._set_zone_from_drag(self._screen_to_world(*ev.pos))
                    self.dragging = False
                elif ev.type == pygame.MOUSEMOTION and self.dragging:
                    self._set_zone_from_drag(self._screen_to_world(*ev.pos))
                elif ev.type == pygame.MOUSEWHEEL:
                    self.zoom = max(0.15, min(3.0, self.zoom * (1.15 if ev.y > 0 else 0.88)))

            keys = pygame.key.get_pressed()
            pan_speed = 500.0 / max(self.zoom, 0.25)
            if keys[pygame.K_LEFT]:
                self.camera_x -= pan_speed / 60.0
            if keys[pygame.K_RIGHT]:
                self.camera_x += pan_speed / 60.0
            if keys[pygame.K_UP]:
                self.camera_y -= pan_speed / 60.0
            if keys[pygame.K_DOWN]:
                self.camera_y += pan_speed / 60.0

            self._draw()
            self.clock.tick(60)

        pygame.quit()


def main():
    parser = argparse.ArgumentParser(description="Tutorial editor")
    parser.add_argument("--map", type=int, default=max(1, int(getattr(const, "MAP_NUM", 1))), help="Map number")
    args = parser.parse_args()
    TutorialEditor(args.map).run()


if __name__ == "__main__":
    main()
