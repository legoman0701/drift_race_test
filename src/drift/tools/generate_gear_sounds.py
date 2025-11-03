#!/usr/bin/env python3
"""
Generate synthetic gear shift sounds for the drift racing game.
Creates aggressive, rough gear shift sounds for manual transmission feel.
"""

import os, numpy as np

def generate_gear_shift_sound(filename, duration=0.25, sample_rate=44100, 
                             noise_intensity=0.3, click_intensity=0.7):
    """Generate a synthetic gear shift sound."""
    
    # Calculate number of samples
    num_samples = int(duration * sample_rate)
    
    # Create time array
    t = np.linspace(0, duration, num_samples)
    
    # Generate base noise (transmission grinding)
    noise = np.random.normal(0, noise_intensity, num_samples)
    
    # Add some metallic clicks/clanks
    click_positions = np.random.randint(0, num_samples, size=max(1, int(num_samples * 0.1)))
    for pos in click_positions:
        if pos < num_samples - 100:
            # Sharp click sound
            click_decay = np.exp(-10 * np.linspace(0, 0.01, 100))
            noise[pos:pos+100] += click_intensity * click_decay * np.random.choice([-1, 1])
    
    # Add some low frequency rumble
    rumble_freq = 60 + np.random.randint(-20, 20)  # 40-80 Hz
    rumble = 0.4 * np.sin(2 * np.pi * rumble_freq * t)
    
    # Combine components
    audio = noise + rumble
    
    # Apply envelope (attack and decay)
    envelope = np.ones_like(audio)
    attack_samples = int(0.05 * sample_rate)  # 50ms attack
    decay_samples = int(0.1 * sample_rate)    # 100ms decay
    
    # Attack
    if attack_samples < len(envelope):
        envelope[:attack_samples] = np.linspace(0, 1, attack_samples)
    
    # Decay
    if decay_samples < len(envelope):
        envelope[-decay_samples:] = np.linspace(1, 0, decay_samples)
    
    audio *= envelope
    
    # Normalize and convert to 16-bit
    audio = np.clip(audio, -1, 1)
    audio_16bit = (audio * 32767).astype(np.int16)
    
    # Save directly as WAV file
    import wave
    with wave.open(filename, 'wb') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_16bit.tobytes())
    
    print(f"Generated gear shift sound: {filename}")


def main():
    """Generate gear shift sound files."""
    
    # Ensure output directory exists
    output_dir = "assets/cars/ae86/sound"
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate different types of gear shift sounds
    
    # Quick, clean shift (low RPM upshift)
    generate_gear_shift_sound(
        f"{output_dir}/gear_shift_1.wav",
        duration=0.2,
        noise_intensity=0.25,
        click_intensity=0.5
    )
    
    # Medium aggressive shift (normal upshift)
    generate_gear_shift_sound(
        f"{output_dir}/gear_shift_2.wav", 
        duration=0.3,
        noise_intensity=0.4,
        click_intensity=0.7
    )
    
    # Very aggressive shift (high RPM or downshift)
    generate_gear_shift_sound(
        f"{output_dir}/gear_shift_3.wav",
        duration=0.35, 
        noise_intensity=0.6,
        click_intensity=0.9
    )
    
    print("All gear shift sounds generated successfully!")


if __name__ == "__main__":
    main()