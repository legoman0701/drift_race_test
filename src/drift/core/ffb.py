"""
Force Feedback (FFB) for real steering wheels.

Uses SDL2 haptic via ctypes, which works with pygame-ce on Windows/Linux/macOS
since pygame-ce bundles SDL2.

When a haptic device is successfully opened, `SteeringFFB.is_active` is True.
The caller should then disable all steering assists (set steer_bias = 0).

Physics: Self-Aligning Torque (SAT) is computed from the front-axle lateral
speed and front grip coefficients.  When the front tyres grip well the wheel
is heavy and wants to re-centre; when they slide (drift) the wheel goes light.
A yaw-rate damping term adds steering "weight" at speed.
"""

import math
import sys
import os
import ctypes
from typing import Optional

# ─── SDL2 constants ────────────────────────────────────────────────────────────
SDL_INIT_HAPTIC      = 0x00001000
SDL_HAPTIC_CONSTANT  = 1          # SDL_HAPTIC_CONSTANT bit
SDL_HAPTIC_INFINITY  = 0xFFFFFFFF
SDL_HAPTIC_CARTESIAN = 1          # direction type: X/Y/Z axes


# ─── SDL2 haptic structs ───────────────────────────────────────────────────────
# These mirror the exact memory layout of SDL_HapticConstant / SDL_HapticEffect.
# Explicit padding fields keep ctypes alignment identical to the C struct.

class _HapticDirection(ctypes.Structure):
    _fields_ = [
        ("type",  ctypes.c_uint8),
        ("_pad",  ctypes.c_uint8 * 3),   # natural alignment for Sint32
        ("dir",   ctypes.c_int32 * 3),   # dir[0]=X dir[1]=Y dir[2]=Z
    ]
    # sizeof = 1 + 3 + 12 = 16 bytes


class _HapticConstant(ctypes.Structure):
    _fields_ = [
        ("type",          ctypes.c_uint16),       # SDL_HAPTIC_CONSTANT
        ("_pad",          ctypes.c_uint16),       # align direction to 4-byte
        ("direction",     _HapticDirection),      # 16 bytes
        ("length",        ctypes.c_uint32),       # duration ms; 0xFFFFFFFF = infinite
        ("delay",         ctypes.c_uint16),
        ("button",        ctypes.c_uint16),
        ("interval",      ctypes.c_uint16),
        ("level",         ctypes.c_int16),        # force: -32768..32767
        ("attack_length", ctypes.c_uint16),
        ("attack_level",  ctypes.c_uint16),
        ("fade_length",   ctypes.c_uint16),
        ("fade_level",    ctypes.c_uint16),
    ]
    # sizeof = 2+2+16+4+2+2+2+2+2+2+2+2 = 42 bytes (padded to 44 in union)


class _HapticEffect(ctypes.Union):
    """SDL_HapticEffect union – padded to 80 bytes to cover all variants safely."""
    _fields_ = [
        ("type",     ctypes.c_uint16),
        ("constant", _HapticConstant),
        ("_pad",     ctypes.c_uint8 * 80),
    ]


# ─── SDL2 DLL loader ──────────────────────────────────────────────────────────

def _load_sdl2() -> Optional[ctypes.CDLL]:
    """Try to find and load the SDL2 shared library."""
    import pygame
    pg_dir = os.path.dirname(pygame.__file__)
    # Directory containing this file (src/drift/core/)
    _core_dir = os.path.dirname(os.path.abspath(__file__))

    if sys.platform == "win32":
        candidates = [
            os.path.join(_core_dir, "SDL2.dll"),  # bundled alongside ffb.py
            os.path.join(pg_dir, "SDL2.dll"),
            "SDL2.dll",
        ]
    elif sys.platform == "darwin":
        candidates = [
            os.path.join(_core_dir, "libSDL2.dylib"),
            os.path.join(pg_dir, "SDL2.dylib"),
            "/usr/local/lib/libSDL2.dylib",
            "/opt/homebrew/lib/libSDL2.dylib",
        ]
    else:
        pg_libs = os.path.join(pg_dir, "libs")
        candidates = [
            os.path.join(_core_dir, "libSDL2-2.0.so.0"),
            os.path.join(_core_dir, "libSDL2.so"),
            os.path.join(pg_libs, "libSDL2-2.0.so.0"),
            "libSDL2-2.0.so.0",
            "libSDL2.so",
        ]

    for path in candidates:
        try:
            lib = ctypes.CDLL(path)
            return lib
        except OSError:
            pass
    return None


def _configure_sdl2(sdl) -> bool:
    """Set argtypes/restype for every SDL2 haptic function we need."""
    try:
        sdl.SDL_InitSubSystem.argtypes            = [ctypes.c_uint32]
        sdl.SDL_InitSubSystem.restype             = ctypes.c_int
        sdl.SDL_WasInit.argtypes                  = [ctypes.c_uint32]
        sdl.SDL_WasInit.restype                   = ctypes.c_uint32
        sdl.SDL_NumHaptics.restype                = ctypes.c_int
        sdl.SDL_HapticOpen.argtypes               = [ctypes.c_int]
        sdl.SDL_HapticOpen.restype                = ctypes.c_void_p
        sdl.SDL_HapticClose.argtypes              = [ctypes.c_void_p]
        sdl.SDL_HapticClose.restype               = None
        sdl.SDL_HapticName.argtypes               = [ctypes.c_int]
        sdl.SDL_HapticName.restype                = ctypes.c_char_p
        sdl.SDL_HapticQuery.argtypes              = [ctypes.c_void_p]
        sdl.SDL_HapticQuery.restype               = ctypes.c_uint
        sdl.SDL_HapticNewEffect.argtypes          = [ctypes.c_void_p, ctypes.c_void_p]
        sdl.SDL_HapticNewEffect.restype           = ctypes.c_int
        sdl.SDL_HapticUpdateEffect.argtypes       = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        sdl.SDL_HapticUpdateEffect.restype        = ctypes.c_int
        sdl.SDL_HapticRunEffect.argtypes          = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
        sdl.SDL_HapticRunEffect.restype           = ctypes.c_int
        sdl.SDL_HapticDestroyEffect.argtypes      = [ctypes.c_void_p, ctypes.c_int]
        sdl.SDL_HapticDestroyEffect.restype       = None
        sdl.SDL_GetError.argtypes                 = []
        sdl.SDL_GetError.restype                  = ctypes.c_char_p
        return True
    except AttributeError as exc:
        print(f"[FFB] SDL2 symbol missing: {exc}")
        return False


# ─── Public API ───────────────────────────────────────────────────────────────

class SteeringFFB:
    """
    Manages a constant-force FFB effect on a real steering wheel.

    Usage:
        ffb = SteeringFFB(joystick_index=0)
        if ffb.is_active:
            # steering assists should be disabled
        # each physics frame:
        ffb.update(my_car, dt)
        # on exit:
        ffb.stop()
    """

    # Half-wheelbase used for front-axle yaw-rate contribution (pixels)
    _HALF_WB = 19.0
    # Front lateral speed at which force saturates (pixels/s)
    _SAT_SPEED_SCALE = 150.0
    # Speed below which force fades to zero (pixels/s)
    _SPEED_RAMP_LOW  = 5.0
    _SPEED_RAMP_HIGH = 50.0
    # Yaw damping contribution (reduces 'light' feel at high yaw rate)
    _YAW_DAMP = 0.15
    # Minimum level change to bother calling SDL_HapticUpdateEffect
    _UPDATE_THRESHOLD = 250   # out of 32767

    def __init__(self, joystick_index: int = 0):
        self.is_active     = False
        self._haptic       = None   # SDL_Haptic* (c_void_p)
        self._effect_id    = -1
        self._sdl2         = None
        self._js_index     = joystick_index
        self._last_level   = 0
        self._try_init()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _try_init(self):
        sdl = _load_sdl2()
        if sdl is None:
            print("[FFB] SDL2 library not found – force feedback disabled")
            return
        if not _configure_sdl2(sdl):
            return
        self._sdl2 = sdl

        # Ensure the SDL2 haptic subsystem is running
        if not (sdl.SDL_WasInit(SDL_INIT_HAPTIC) & SDL_INIT_HAPTIC):
            ret = sdl.SDL_InitSubSystem(SDL_INIT_HAPTIC)
            if ret != 0:
                err = sdl.SDL_GetError()
                print(f"[FFB] SDL_InitSubSystem(haptic) failed: {err.decode() if err else '?'}")
                return

        # Get joystick name from pygame to match against haptic devices
        try:
            import pygame
            js = pygame.joystick.Joystick(self._js_index)
            js_name = js.get_name()
        except Exception as exc:
            print(f"[FFB] Could not read joystick name: {exc}")
            return

        haptic = self._find_haptic(sdl, js_name)
        if haptic is None:
            print(f"[FFB] No haptic device matched joystick '{js_name}' – FFB disabled")
            return

        # Verify SDL_HAPTIC_CONSTANT is supported
        caps = sdl.SDL_HapticQuery(haptic)
        if not (caps & SDL_HAPTIC_CONSTANT):
            print(f"[FFB] SDL_HAPTIC_CONSTANT not supported (caps=0x{caps:08X})")
            sdl.SDL_HapticClose(haptic)
            return

        effect_id = self._create_constant_effect(sdl, haptic)
        if effect_id < 0:
            sdl.SDL_HapticClose(haptic)
            return

        ret = sdl.SDL_HapticRunEffect(haptic, effect_id, SDL_HAPTIC_INFINITY)
        if ret < 0:
            err = sdl.SDL_GetError()
            print(f"[FFB] SDL_HapticRunEffect failed: {err.decode() if err else '?'}")
            sdl.SDL_HapticDestroyEffect(haptic, effect_id)
            sdl.SDL_HapticClose(haptic)
            return

        self._haptic    = haptic
        self._effect_id = effect_id
        self.is_active  = True
        print(f"[FFB] Force feedback active on '{js_name}'")

    def _find_haptic(self, sdl, js_name: str):
        """Return an open SDL_Haptic* matching js_name, or the first available device."""
        num = sdl.SDL_NumHaptics()
        if num <= 0:
            print("[FFB] No haptic devices found")
            return None

        # Collect names first so we can print them for diagnostics
        names: list[str] = []
        for i in range(num):
            raw = sdl.SDL_HapticName(i)
            names.append(raw.decode("utf-8", errors="replace") if raw else "")
        print(f"[FFB] Haptic devices ({num}): {names}")

        # Normalise: strip parens/hyphens so 'FFBeast(Wheel)' → 'ffbeast wheel'
        def _norm(s: str) -> str:
            return s.lower().replace("(", " ").replace(")", " ").replace("-", " ").replace("_", " ")

        jl = _norm(js_name)
        js_words = {w for w in jl.split() if len(w) >= 3}

        for i, h_name in enumerate(names):
            hl = _norm(h_name)
            hl_words = {w for w in hl.split() if len(w) >= 3}
            # substring match in either direction, OR at least one significant word in common
            if jl in hl or hl in jl or bool(js_words & hl_words):
                h = sdl.SDL_HapticOpen(i)
                if h:
                    print(f"[FFB] Matched haptic device {i}: '{h_name}'")
                    return h

        # Fallback: use the first openable haptic device regardless of name
        for i, h_name in enumerate(names):
            h = sdl.SDL_HapticOpen(i)
            if h:
                print(f"[FFB] No name match for '{js_name}'; using first haptic device: '{h_name}'")
                return h
        return None

    def _create_constant_effect(self, sdl, haptic) -> int:
        """Create a zero-level constant force effect; return effect_id or -1."""
        eff = _HapticEffect()
        eff.type                          = SDL_HAPTIC_CONSTANT
        eff.constant.type                 = SDL_HAPTIC_CONSTANT
        eff.constant.direction.type       = SDL_HAPTIC_CARTESIAN
        eff.constant.direction.dir[0]     = 1   # X axis (left / right)
        eff.constant.direction.dir[1]     = 0
        eff.constant.direction.dir[2]     = 0
        eff.constant.length               = SDL_HAPTIC_INFINITY
        eff.constant.delay                = 0
        eff.constant.button               = 0
        eff.constant.interval             = 0
        eff.constant.level                = 0
        eff.constant.attack_length        = 0
        eff.constant.attack_level         = 0
        eff.constant.fade_length          = 0
        eff.constant.fade_level           = 0

        eid = sdl.SDL_HapticNewEffect(haptic, ctypes.byref(eff))
        if eid < 0:
            err = sdl.SDL_GetError()
            print(f"[FFB] SDL_HapticNewEffect failed: {err.decode() if err else '?'}")
        return eid

    # ── Per-frame update ──────────────────────────────────────────────────────

    def update(self, car, dt: float):
        """
        Compute the self-aligning torque from car physics and push it to the wheel.

        Call once per physics frame, after car.step().
        """
        if not self.is_active or self._haptic is None:
            return

        import drift.config.const as const

        ca = math.cos(car.angle)
        sa = math.sin(car.angle)

        body_fwd = car.vx * ca + car.vy * sa
        body_lat = car.vx * (-sa) + car.vy * ca
        speed    = math.hypot(car.vx, car.vy)

        # Front-axle lateral velocity (body lateral + yaw contribution at front axle)
        front_lat = body_lat + car.v_angle * self._HALF_WB

        # Average front grip (FL=0, FR=1)
        front_grip = (
            (car.has_grip[0] + car.has_grip[1]) * 0.5
            if len(car.has_grip) >= 2 else 1.0
        )

        # Self-aligning torque: oppose front lateral slip, scaled by grip
        raw_sat = -front_lat * front_grip
        sat_norm = max(-1.0, min(1.0, raw_sat / self._SAT_SPEED_SCALE))

        # Speed ramp: zero force at standstill, full force above ramp_high
        speed_factor = max(0.0, min(1.0,
            (speed - self._SPEED_RAMP_LOW) / (self._SPEED_RAMP_HIGH - self._SPEED_RAMP_LOW)
        ))

        # Yaw damping: adds "weight" – resists spinning the wheel when the car rotates
        yaw_damp = max(-0.3, min(0.3, car.v_angle * self._YAW_DAMP))

        sat_final = (sat_norm + yaw_damp) * speed_factor * const.FFB_STRENGTH
        sat_final = max(-1.0, min(1.0, sat_final))

        level = int(sat_final * 32767)
        if abs(level - self._last_level) < self._UPDATE_THRESHOLD:
            return
        self._last_level = level

        eff = _HapticEffect()
        eff.type                          = SDL_HAPTIC_CONSTANT
        eff.constant.type                 = SDL_HAPTIC_CONSTANT
        eff.constant.direction.type       = SDL_HAPTIC_CARTESIAN
        eff.constant.direction.dir[0]     = 1
        eff.constant.direction.dir[1]     = 0
        eff.constant.direction.dir[2]     = 0
        eff.constant.length               = SDL_HAPTIC_INFINITY
        eff.constant.delay                = 0
        eff.constant.button               = 0
        eff.constant.interval             = 0
        eff.constant.level                = level
        eff.constant.attack_length        = 0
        eff.constant.attack_level         = 0
        eff.constant.fade_length          = 0
        eff.constant.fade_level           = 0

        self._sdl2.SDL_HapticUpdateEffect(
            self._haptic, self._effect_id, ctypes.byref(eff)
        )

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def stop(self):
        """Stop the effect and close the haptic device."""
        if self._sdl2 is None or self._haptic is None:
            return
        if self._effect_id >= 0:
            self._sdl2.SDL_HapticDestroyEffect(self._haptic, self._effect_id)
            self._effect_id = -1
        self._sdl2.SDL_HapticClose(self._haptic)
        self._haptic   = None
        self.is_active = False
        print("[FFB] Force feedback stopped")

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass
