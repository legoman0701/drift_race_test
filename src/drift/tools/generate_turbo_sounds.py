#!/usr/bin/env python3
"""
Audacity Automation Script for Turbo Sound Generation
Generates multiple speed variations of a turbo sound file.

Usage:
1. Install audacity-scripting: pip install pipecat-audacity
2. Run this script while Audacity is open
3. Import your base turbo sound into Audacity first
4. Run the script to generate variations

Alternative: Use as standalone with pydub
"""

import os
import sys
from typing import List, Tuple

# Try to import Audacity scripting support
try:
    from audacity_scripting import AudacityClient
    AUDACITY_AVAILABLE = True
except ImportError:
    AUDACITY_AVAILABLE = False
    print("Audacity scripting not available. Install with: pip install audacity-scripting")

# Try to import pydub for standalone processing
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("Pydub not available for standalone processing. Install with: pip install pydub")


class TurboSoundGenerator:
    """Generate turbo sound variations at different speeds."""
    
    def __init__(self, base_speed: float = 1.0, max_speed: float = 5.0, increment: float = 0.1, target_duration_ms: int = 14000):
        self.base_speed = base_speed
        self.max_speed = max_speed
        self.increment = increment
        self.target_duration_ms = target_duration_ms
    
    def calculate_speed_variations(self) -> List[float]:
        """Calculate all speed variations to generate."""
        speeds = []
        current_speed = self.base_speed
        
        while current_speed <= self.max_speed:
            speeds.append(round(current_speed, 2))
            current_speed += self.increment
        
        return speeds
    
    def generate_with_audacity(self, output_dir: str = "generated_turbo_sounds"):
        """Generate turbo variations using Audacity."""
        if not AUDACITY_AVAILABLE:
            raise RuntimeError("Audacity scripting not available")
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Connect to Audacity
        client = AudacityClient()
        
        speeds = self.calculate_speed_variations()
        print(f"Generating {len(speeds)} turbo sound variations...")
        print(f"Target duration: {self.target_duration_ms/1000:.2f}s")
        
        for i, speed in enumerate(speeds):
            print(f"Processing variation {i+1}/{len(speeds)}: speed {speed}x")
            
            # Select all audio
            client.do("SelectAll:")
            
            # Change speed effect
            speed_percentage = (speed - 1.0) * 100
            client.do(f"ChangeSpeed:Percentage={speed_percentage}")
            
            # Get the new length after speed change
            # Note: This is approximate - Audacity scripting has limitations
            # For precise looping, recommend using the pydub method
            
            # For now, just export as-is
            # TODO: Add looping logic when Audacity scripting supports it better
            
            # Export the file
            filename = f"turbo_speed_{speed:.1f}.wav"
            filepath = os.path.join(output_dir, filename)
            client.do(f"Export2:Filename={filepath}")
            
            # Undo the speed change to reset for next iteration
            client.do("Undo:")
        
        print(f"Generated {len(speeds)} turbo sound variations in '{output_dir}'")
        print("Note: Audacity method doesn't support automatic looping to 14s.")
        print("For precise 14s looping, use the pydub method instead.")
    
    def generate_with_pydub(self, input_file: str, output_dir: str = "generated_turbo_sounds"):
        """Generate turbo variations using pydub (standalone)."""
        if not PYDUB_AVAILABLE:
            raise RuntimeError("Pydub not available")
        
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input file not found: {input_file}")
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Load the audio file
        print(f"Loading audio file: {input_file}")
        audio = AudioSegment.from_file(input_file)
        original_duration_ms = len(audio)
        
        speeds = self.calculate_speed_variations()
        print(f"Generating {len(speeds)} turbo sound variations...")
        print(f"Original audio duration: {original_duration_ms/1000:.2f}s")
        print(f"Target duration: {self.target_duration_ms/1000:.2f}s")
        
        for i, speed in enumerate(speeds):
            print(f"Processing variation {i+1}/{len(speeds)}: speed {speed}x")
            
            # Change speed by adjusting frame rate
            # Speed up = higher frame rate, slow down = lower frame rate
            new_sample_rate = int(audio.frame_rate * speed)
            
            # Create new audio with changed speed
            speed_audio = audio._spawn(audio.raw_data, overrides={"frame_rate": new_sample_rate})
            speed_audio = speed_audio.set_frame_rate(audio.frame_rate)
            
            # Calculate how long the sped-up audio is
            speed_duration_ms = len(speed_audio)
            
            # Loop the audio to reach target duration
            if speed_duration_ms < self.target_duration_ms:
                # Calculate how many loops we need
                loops_needed = int(self.target_duration_ms / speed_duration_ms) + 1
                print(f"  Looping {loops_needed} times to reach {self.target_duration_ms/1000:.2f}s")
                
                # Create looped audio
                looped_audio = speed_audio
                for _ in range(loops_needed - 1):
                    looped_audio += speed_audio
                
                # Trim to exact target duration
                final_audio = looped_audio[:self.target_duration_ms]
            else:
                # Audio is already longer than target, just trim
                print(f"  Trimming to {self.target_duration_ms/1000:.2f}s")
                final_audio = speed_audio[:self.target_duration_ms]
            
            # Export the file
            filename = f"turbo_speed_{speed:.1f}.wav"
            filepath = os.path.join(output_dir, filename)
            final_audio.export(filepath, format="wav")
            
            print(f"  Generated: {filename} ({len(final_audio)/1000:.2f}s)")
        
        print(f"Generated {len(speeds)} turbo sound variations in '{output_dir}'")
        print(f"All files are exactly {self.target_duration_ms/1000:.2f} seconds long")


def main():
    """Main function to run the turbo sound generator."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate turbo sound speed variations")
    parser.add_argument("--input", "-i", help="Input audio file (for pydub mode)")
    parser.add_argument("--output", "-o", default="generated_turbo_sounds", 
                       help="Output directory (default: generated_turbo_sounds)")
    parser.add_argument("--base-speed", type=float, default=1.0, 
                       help="Base speed multiplier (default: 1.0)")
    parser.add_argument("--max-speed", type=float, default=5.0,
                       help="Maximum speed multiplier (default: 5.0)")
    parser.add_argument("--increment", type=float, default=0.1,
                       help="Speed increment (default: 0.1)")
    parser.add_argument("--duration", type=float, default=14.0,
                       help="Target duration in seconds (default: 14.0)")
    parser.add_argument("--method", choices=["audacity", "pydub"], default="pydub",
                       help="Generation method (default: pydub)")
    
    args = parser.parse_args()
    
    # Create generator
    generator = TurboSoundGenerator(
        base_speed=args.base_speed,
        max_speed=args.max_speed,
        increment=args.increment,
        target_duration_ms=int(args.duration * 1000)
    )
    
    try:
        if args.method == "audacity":
            if not AUDACITY_AVAILABLE:
                print("Error: Audacity scripting not available")
                print("Install with: pip install pipecat-audacity")
                return 1
            
            print("Using Audacity method...")
            print("Make sure Audacity is open with your turbo sound loaded!")
            input("Press Enter to continue...")
            generator.generate_with_audacity(args.output)
        
        elif args.method == "pydub":
            if not PYDUB_AVAILABLE:
                print("Error: Pydub not available")
                print("Install with: pip install pydub")
                return 1
            
            if not args.input:
                print("Error: Input file required for pydub method")
                print("Use: --input path/to/your/turbo_sound.wav")
                return 1
            
            print("Using pydub method...")
            generator.generate_with_pydub(args.input, args.output)
        
        print("\n✓ Turbo sound generation completed successfully!")
        
        # Show generated files
        if os.path.exists(args.output):
            files = [f for f in os.listdir(args.output) if f.startswith("turbo_speed_")]
            files.sort()
            print(f"\nGenerated files in '{args.output}':")
            for file in files:
                print(f"  {file}")
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())