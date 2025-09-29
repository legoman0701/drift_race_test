"""
Engine sound blending for RPM using BeamNG-style sfxBlend2D JSON.

This module provides EngineSoundBlend which:
- Loads one or more rows of RPM-indexed loop samples from a .sfxBlend2D.json
- Keeps each sample playing on a dedicated mixer Channel at 0 volume (always running, stays in sync)
- Crossfades volumes between nearest RPM samples each frame
- Mixes OFF/coast layer vs ON/throttle layer based on current throttle

Assumptions and simplifications
- We treat row 0 (WAVs like 2950.wav, 4250.wav, ...) as ON/throttle layer
- We treat row 1 (idle.flac, on1.flac, on2.flac, on3.flac) as OFF/idle/coast layer
- All samples are looped; ensure assets are loop-ready to avoid clicks
- FLAC may not be supported on some systems; files that fail to load are skipped

Paths
- BeamNG paths like "art/sound/engine/4AGE_TODA/2950.wav" are mapped to
  "assets/AE86/sound/4AGE_TODA/2950.wav" by default. Override via root_map.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Optional
import json
import os

try:
	import pygame_ce as pygame
except Exception:  # pragma: no cover
	import pygame  # type: ignore


@dataclass
class _RowSample:
	rpm: float
	path: str
	sound: Optional[pygame.mixer.Sound]
	channel_index: int
	volume: float = 0.0


class EngineSoundBlend:
	def __init__(
		self,
		blend_json_path: str,
	root_map: Optional[Tuple[str, str]] = ("art/sound/engine/4AGE_TODA", "assets/AE86/sound/4AGE_TODA"),
	base_gain: float = 0.2,  # OFF/coast layer gain (row 1)
	on_gain: float = 1.0,     # ON/throttle layer gain (row 0)
		vol_slew_per_s: float = 2.5,
	) -> None:
		"""
		Create an engine sound blender from a sfxBlend2D JSON.

		- blend_json_path: Path to JSON
		- root_map: (from_prefix, to_prefix) to rewrite sample paths
		- base_gain: gain for row 0 (steady) [0..1]
		- on_gain: gain for row 1 (on/throttle) [0..1]
		- vol_slew_per_s: max volume change per second per sample
		"""
		self.base_gain = base_gain
		self.on_gain = on_gain
		self.vol_slew_per_s = vol_slew_per_s
		self.rows = []  # type: List[List[_RowSample]]
		# Map of global sample index -> sample rpm for idle-like samples
		self._idle_samples = {}  # type: dict[int, float]
		self.started = False

		self._ensure_mixer()

		data = self._load_json(blend_json_path)
		samples = data.get("samples") or []

		# Flatten and count to reserve enough mixer channels
		total_samples = 0
		for row in samples:
			total_samples += len(row)
		if total_samples <= 0:
			print("[EngineSoundBlend] No samples in blend JSON:", blend_json_path)
			return

		# Make sure the mixer has enough channels to keep all loops resident
		current_channels = pygame.mixer.get_num_channels()
		if current_channels < total_samples:
			pygame.mixer.set_num_channels(total_samples)

		# Load rows
		chan_cursor = 0
		from_pref, to_pref = (root_map or ("", ""))
		for row in samples:
			print(row)
			row_list: List[_RowSample] = []
			for entry in row:
				try:
					rel_path, rpm = entry[0], float(entry[1])
				except Exception:
					# skip malformed row entries
					continue
				resolved = self._map_path(rel_path, from_pref, to_pref)
				snd = None
				if os.path.isfile(resolved):
					try:
						snd = pygame.mixer.Sound(resolved)
					except Exception as e:
						print(f"[EngineSoundBlend] Failed to load {resolved}: {e}")
				else:
					print(f"[EngineSoundBlend] Missing sample: {resolved}")
				row_list.append(_RowSample(rpm=rpm, path=resolved, sound=snd, channel_index=chan_cursor))
				chan_cursor += 1

			# Sort by RPM just in case
			row_list.sort(key=lambda s: s.rpm)
			self.rows.append(row_list)

		# Kick off loops with volume 0 (all channels play forever so they stay synced)
		self._start_all()

	def _ensure_mixer(self) -> None:
		if not pygame.mixer.get_init():
			# Reasonable defaults
			try:
				pygame.mixer.pre_init(44100, size=-16, channels=2, buffer=512)
			except Exception:
				pass
			pygame.mixer.init()

	def _load_json(self, path: str) -> dict:
		with open(path, "r", encoding="utf-8") as f:
			return json.load(f)

	def _map_path(self, rel_path: str, from_pref: str, to_pref: str) -> str:
		# Normalize separators
		rel_norm = rel_path.replace("\\", "/")
		if from_pref and rel_norm.startswith(from_pref):
			rel_norm = to_pref + rel_norm[len(from_pref):]
		# Ensure OS path
		return os.path.normpath(rel_norm)

	def _start_all(self) -> None:
		chan_count = pygame.mixer.get_num_channels()
		for row in self.rows:
			for s in row:
				if s.sound is None:
					continue
				if s.channel_index >= chan_count:
					continue
				ch = pygame.mixer.Channel(s.channel_index)
				try:
					ch.play(s.sound, loops=-1)
				except Exception as e:
					print(f"[EngineSoundBlend] Failed to play loop {s.path}: {e}")
				ch.set_volume(0.0)
				s.volume = 0.0
		self.started = True

	def stop(self, fade_ms: int = 200) -> None:
		for row in self.rows:
			for s in row:
				if s.sound is None:
					continue
				ch = pygame.mixer.Channel(s.channel_index)
				try:
					ch.fadeout(fade_ms)
				except Exception:
					pass
		self.started = False

	def update(self, rpm: float, throttle: float, dt: float) -> None:
		if not self.started or not self.rows:
			return
		throttle = max(0.0, min(1.0, throttle))

		# Row mapping: row 0 = ON/throttle, row 1 = OFF/coast
		on_row = self.rows[0] if len(self.rows) >= 1 else []
		off_row = self.rows[1] if len(self.rows) >= 2 else []

		on_weights = self._rpm_weights(on_row, rpm) if on_row else {}
		off_weights = self._rpm_weights(off_row, rpm) if off_row else {}

		# Compute target volumes per sample index
		target_vol: dict[int, float] = {}
		# Equal-power crossfade to keep perceived loudness even
		# t_on and t_off are sqrt-shaped
		import math
		t_on = math.sqrt(max(0.0, min(1.0, throttle)))
		t_off = math.sqrt(max(0.0, min(1.0, 1.0 - throttle)))

		# OFF/coast layer scaled by t_off
		for idx, w in off_weights.items():
			target_vol[idx] = target_vol.get(idx, 0.0) + w * (self.base_gain * t_off)
		# ON/throttle layer scaled by t_on
		for idx, w in on_weights.items():
			target_vol[idx] = target_vol.get(idx, 0.0) + w * (self.on_gain * t_on)

		# Slew and apply
		dv_max = self.vol_slew_per_s * dt
		chan_count = pygame.mixer.get_num_channels()

		# Iterate all samples and push volumes
		cursor = 0
		for row in self.rows:
			for s in row:
				if s.sound is None:
					cursor += 1
					continue
				if s.channel_index >= chan_count:
					cursor += 1
					continue
				tgt = max(0.0, min(1.0, target_vol.get(cursor, 0.0)))
				# Slightly attenuate the specific idle sample to avoid dominance
				try:
					base = os.path.basename(s.path).lower() if s.path else ""
					if "idle" in base:
						# Gentle attenuation for idle loop
						tgt *= 0.75
				except Exception:
					pass
				cur = s.volume
				dv = max(-dv_max, min(dv_max, tgt - cur))
				new_v = max(0.0, min(1.0, cur + dv))
				if abs(new_v - cur) >= 1e-4:
					pygame.mixer.Channel(s.channel_index).set_volume(new_v)
					s.volume = new_v
				cursor += 1

	def _rpm_weights(self, row: List[_RowSample], rpm: float) -> dict[int, float]:
		if not row:
			return {}
		# Below first or above last -> weight fully to nearest
		if rpm <= row[0].rpm:
			# weight entirely to first in row
			idx0 = self._global_index(row, 0)
			return {idx0: 1.0}
		if rpm >= row[-1].rpm:
			idxN = self._global_index(row, len(row)-1)
			return {idxN: 1.0}

		# Find bracket
		lo = 0
		hi = len(row) - 1
		while hi - lo > 1:
			mid = (lo + hi) // 2
			if rpm < row[mid].rpm:
				hi = mid
			else:
				lo = mid
		r0, r1 = row[lo], row[hi]
		t = (rpm - r0.rpm) / max(1e-6, (r1.rpm - r0.rpm))
		idx0 = self._global_index(row, lo)
		idx1 = self._global_index(row, hi)
		return {idx0: 1.0 - t, idx1: t}

	def _global_index(self, row: List[_RowSample], idx_in_row: int) -> int:
		# Convert row-local index to global channel cursor index order used in update()
		offset = 0
		for r in self.rows:
			if r is row:
				break
			offset += len(r)
		return offset + idx_in_row


__all__ = ["EngineSoundBlend"]
