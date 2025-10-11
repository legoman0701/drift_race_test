import os, sys, math, pygame, numpy as np

SAMPLE_RATE = 48000
CHUNK_SAMPLES = 2048  # ~42.7 ms at 48kHz
MIX_CHANNELS = 2      # stereo
BITS = -16            # signed 16-bit

def clamp(x, a, b):
    return a if x < a else b if x > b else x

class OnePoleLPF:
    def __init__(self, alpha=0.2, x0=0.0):
        self.a = clamp(alpha, 0.0, 1.0)
        self.y = float(x0)

    def reset(self, x0=0.0):
        self.y = float(x0)

    def step(self, x):
        self.y = self.a * x + (1.0 - self.a) * self.y
        return self.y

class TurboWhine:
    """
    Real-time looping, pitch-shifted turbo whine using numpy resampling and pygame mixer.
    """
    def __init__(self, wav_path, rpm_base=40000.0, rpm_min=15000.0, rpm_max=140000.0,
                 vol_lpf_alpha=0.25):
        self.rpm_base = rpm_base
        self.rpm_min = rpm_min
        self.rpm_max = rpm_max
        self.phase = 0.0  # fractional index into source
        self.channel = pygame.mixer.Channel(0)
        self.channel.set_volume(1.0, 1.0)

        # Load source as mono float32 in range [-1, 1]
        snd = pygame.mixer.Sound(wav_path)
        arr = pygame.sndarray.array(snd)  # shape (N,) mono or (N,2) stereo
        if arr.ndim == 2:
            arr = arr.mean(axis=1)  # downmix to mono
        # Normalize if integer type
        if arr.dtype == np.int16:
            src = arr.astype(np.float32) / 32768.0
        elif arr.dtype == np.int8:
            src = arr.astype(np.float32) / 128.0
        else:
            src = arr.astype(np.float32)
        # Remove DC offset
        src = src - np.mean(src)
        # Gentle fade to ensure seamless loop
        fade = min(1024, src.shape[0] // 20)
        if fade > 0:
            w = np.linspace(0, 1, fade, dtype=np.float32)
            src[:fade] *= w
            src[-fade:] *= (1.0 - w)
        self.src = src
        self.N = len(src)
        if self.N < 1024:
            raise RuntimeError("Turbo source too short; need > 1024 samples.")

        # Volume smoothing
        self.vol_lpf = OnePoleLPF(alpha=vol_lpf_alpha, x0=0.0)

        # Queue priming flag
        self._primed = False

    def rpm_to_ratio(self, rpm):
        # Map RPM to playback rate ratio relative to the recording’s apparent base
        r = clamp(rpm, self.rpm_min, self.rpm_max)
        ratio = r / self.rpm_base -2
        return clamp(ratio, 0.02, 3.0)  # keep safe range (1 octave down .. ~+1.6 octaves)

    def amp_for_state(self, rpm, throttle):
        # Simple loudness curve: louder with rpm and throttle; floor to avoid silence when spooling
        norm = (clamp(rpm, self.rpm_min, self.rpm_max) - self.rpm_min) / (self.rpm_max - self.rpm_min + 1e-9)
        base = norm ** 0.75
        loud = 0.15 + 0.85 * (0.35 * base + 0.65 * clamp(throttle, 0.0, 1.0))
        return clamp(loud, 0.0, 1.0)

    def _make_chunk(self, rate_ratio, volume):
        # Vectorized fractional resampling with wrap-around
        n = CHUNK_SAMPLES
        N = self.N
        src = self.src

        # positions for each output sample
        pos = (self.phase + rate_ratio * np.arange(n, dtype=np.float32)) % N
        i0 = np.floor(pos).astype(np.int32)
        i1 = (i0 + 1) % N
        frac = pos - i0

        # Linear interpolation
        out = src[i0] + (src[i1] - src[i0]) * frac

        # Advance phase for next call
        self.phase = float((pos[-1] + rate_ratio) % N)

        # Apply volume and convert to int16 stereo
        out = np.clip(out * volume, -1.0, 1.0).astype(np.float32)
        stereo = np.repeat(out[:, None], 2, axis=1)  # (n, 2)
        pcm = (stereo * 32767.0).astype(np.int16)
        return pygame.sndarray.make_sound(pcm)

    def update(self, rpm, throttle):
        # Compute playback params
        rate_ratio = self.rpm_to_ratio(rpm)
        target_amp = self.amp_for_state(rpm, throttle)
        amp = self.vol_lpf.step(target_amp)

        if not self._primed:
            # Start playback and queue one extra chunk to avoid gaps
            a = self._make_chunk(rate_ratio, amp)
            b = self._make_chunk(rate_ratio, amp)
            self.channel.play(a)
            self.channel.queue(b)
            self._primed = True
            return

        # If no queued buffer, queue the next chunk
        if self.channel.get_queue() is None:
            nxt = self._make_chunk(rate_ratio, amp)
            self.channel.queue(nxt)

class TurboDemo:
    def __init__(self, wav_path):
        self.turbo = TurboWhine(wav_path)
        self.throttle = 0.0
        self.turbo_rpm = 20000.0
        self.clock = pygame.time.Clock()
        # Spool dynamics (seconds)
        self.tau_spool_up = 0.20
        self.tau_spool_down = 0.40

        # Simple window just to capture input and show stats
        self.screen = pygame.display.set_mode((640, 200))
        pygame.display.set_caption("Turbo Whine Demo")

        try:
            self.font = pygame.font.SysFont(None, 24)
        except Exception:
            self.font = None

    def step_physics(self, dt):
        # Target turbo RPM based on throttle
        tgt = self.turbo.rpm_min + self.throttle * (self.turbo.rpm_max - self.turbo.rpm_min)
        tau = self.tau_spool_up if tgt > self.turbo_rpm else self.tau_spool_down
        # First-order approach
        alpha = 1.0 - math.exp(-dt / max(1e-4, tau))
        self.turbo_rpm += (tgt - self.turbo_rpm) * alpha

    def draw(self):
        self.screen.fill((15, 15, 20))
        if self.font:
            txt = f"Throttle: {self.throttle:.2f}   Turbo RPM: {int(self.turbo_rpm):>6d}   Rate: {self.turbo.rpm_to_ratio(self.turbo_rpm):.2f}"
            surf = self.font.render(txt, True, (220, 230, 245))
            self.screen.blit(surf, (16, 16))
        pygame.display.flip()

    def run(self):
        running = True
        # Prime a few updates to fill the queue right away
        for _ in range(2):
            self.turbo.update(self.turbo_rpm, self.throttle)

        while running:
            dt = self.clock.tick(60) / 1000.0

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False

            # Continuous input (hold keys)
            keys = pygame.key.get_pressed()
            # Up arrow increases throttle, Down decreases
            inc = 0.9 if keys[pygame.K_UP] else -0.9 if keys[pygame.K_DOWN] else 0.0
            self.throttle = clamp(self.throttle + inc * dt, 0.0, 1.0)
            # Natural decay if no keys pressed
            if inc == 0.0:
                self.throttle = max(0.0, self.throttle - 0.5 * dt)

            self.step_physics(dt)
            self.turbo.update(self.turbo_rpm, self.throttle)
            self.draw()

def find_sample_path():
    # Try a few likely locations
    candidates = [
        os.path.join(os.getcwd(), "TWhine1.wav"),
        os.path.join(os.getcwd(), "assets", "audio", "TWhine1.wav"),
        os.path.join(os.path.dirname(__file__), "TWhine1.wav"),
        os.path.join(os.path.dirname(__file__), "assets", "audio", "TWhine1.wav"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

def main():
    pygame.mixer.pre_init(SAMPLE_RATE, BITS, MIX_CHANNELS, 512)
    pygame.init()
    pygame.mixer.set_num_channels(8)

    wav_path = find_sample_path()
    if wav_path is None:
        print("TWhine1.wav not found. Place it next to this file or in assets/audio/TWhine1.wav")
        return 1

    demo = TurboDemo(wav_path)
    demo.run()
    pygame.quit()
    return 0

if __name__ == "__main__":
    sys.exit(main())