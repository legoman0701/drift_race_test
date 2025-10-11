#!/usr/bin/env python3
"""
Test script for the threaded audio system.

This script demonstrates how to use the new audio thread functionality
to prevent audio clipping when FPS drops occur in the main game loop.
"""

import time, math, pygame
from src.drift.audio.engine_audio import EngineAudio

def test_threaded_audio():
    """Test the threaded audio system with simulated FPS drops."""
    
    # Initialize pygame mixer (required for audio)
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.mixer.init()
    
    print("Testing threaded audio system...")
    
    try:
        # Create engine audio instance
        engine_audio = EngineAudio(
            engine_master_volume=0.3,  # Lower volume for testing
            turbo_master_volume=0.2,
            enable_turbo=True,
            enable_bov=True
        )
        
        # Start the audio thread (runs at 100 Hz by default)
        engine_audio.start_audio_thread(update_rate=100.0)
        
        print("Audio thread started. Testing with varying engine conditions...")
        
        # Simulate game loop with varying conditions
        start_time = time.perf_counter()
        
        while time.perf_counter() - start_time < 10.0:  # Run for 10 seconds
            current_time = time.perf_counter() - start_time
            
            # Simulate varying RPM (0-8000)
            rpm = 1000 + abs(4000 * (1 + 0.8 * math.sin(current_time * 0.7)))
            
            # Simulate throttle (0-1)
            throttle = max(0, 0.5 + 0.5 * math.sin(current_time * 1.2))
            
            # Update engine state (thread-safe)
            engine_audio.set_engine_state(rpm, throttle)
            
            # Simulate FPS drops every 3 seconds
            if int(current_time) % 3 == 0 and current_time % 1 < 0.1:
                print(f"[{current_time:.1f}s] Simulating FPS drop (200ms stall)...")
                time.sleep(0.2)  # Simulate 200ms frame hitch
            
            # Print status every 2 seconds
            if int(current_time * 2) % 4 == 0 and current_time % 0.5 < 0.05:
                print(f"[{current_time:.1f}s] RPM: {rpm:.0f}, Throttle: {throttle:.2f}")
            
            # Normal game frame rate (60 FPS target)
            time.sleep(1.0 / 60.0)
        
        print("\\nTest completed. Audio should have remained smooth despite FPS drops.")
        
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean shutdown
        if 'engine_audio' in locals():
            engine_audio.stop_all()
        pygame.mixer.quit()
        print("Audio system stopped.")

def test_comparison():
    """Compare threaded vs non-threaded audio behavior."""
    
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.mixer.init()
    
    print("\\n=== Comparison Test ===")
    
    try:
        engine_audio = EngineAudio(
            engine_master_volume=0.2,
            turbo_master_volume=0.15,
            enable_turbo=True
        )
        
        print("1. Testing WITHOUT audio thread (traditional mode)...")
        
        # Test without thread (traditional direct updates)
        start_time = time.perf_counter()
        last_update = start_time
        
        while time.perf_counter() - start_time < 5.0:
            current_time = time.perf_counter()
            dt = current_time - last_update
            last_update = current_time
            
            rpm = 2000 + 3000 * abs(math.sin(current_time * 0.5))
            throttle = 0.3 + 0.7 * abs(math.cos(current_time * 0.8))
            
            # Direct update (frame-locked)
            engine_audio.update(rpm, throttle, dt)
            
            # Simulate occasional FPS drop
            if int(current_time * 4) % 10 == 0:
                time.sleep(0.1)  # 100ms hitch
            
            time.sleep(1.0 / 60.0)
        
        print("2. Testing WITH audio thread (smooth mode)...")
        
        # Start audio thread
        engine_audio.start_audio_thread(update_rate=120.0)
        
        start_time = time.perf_counter()
        
        while time.perf_counter() - start_time < 5.0:
            current_time = time.perf_counter() - start_time
            
            rpm = 2000 + 3000 * abs(math.sin(current_time * 0.5))
            throttle = 0.3 + 0.7 * abs(math.cos(current_time * 0.8))
            
            # Thread-safe state update
            engine_audio.set_engine_state(rpm, throttle)
            
            # Simulate occasional FPS drop
            if int(current_time * 4) % 10 == 0:
                time.sleep(0.1)  # 100ms hitch
            
            time.sleep(1.0 / 60.0)
        
        print("Comparison complete. Audio thread should provide smoother audio.")
        
    except Exception as e:
        print(f"Comparison test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if 'engine_audio' in locals():
            engine_audio.stop_all()
        pygame.mixer.quit()

if __name__ == "__main__":
    print("Threaded Audio System Test")
    print("=" * 40)
    
    # Run basic test
    test_threaded_audio()
    
    # Run comparison test
    test_comparison()
    
    print("\\nAll tests completed!")