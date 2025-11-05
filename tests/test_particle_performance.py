"""
Test script for the optimized particle system.
Run this to verify the particle system works correctly and measure performance.
"""

import pygame
import sys
import os
import time
import math
import random

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from drift.render.particles import ParticleSystem, ParticleEmitter
    from drift.render.camera import Camera
    from drift.render.racing_effects import RacingParticleEffects
    import drift.config.const as const
except ImportError as e:
    print(f"Import error: {e}")
    print("Make sure you're running this from the project root directory")
    sys.exit(1)


def test_particle_performance():
    """Test particle system performance with various particle counts."""
    pygame.init()
    
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Particle System Performance Test")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 24)
    
    # Create systems
    camera = Camera(800, 600, zoom=1.0)
    particle_system = ParticleSystem(max_particles=10000)
    racing_effects = RacingParticleEffects(particle_system)
    
    # Test parameters
    test_mode = 1  # 0=burst, 1=continuous, 2=racing effects
    test_modes = ["Burst Test", "Continuous Test", "Racing Effects Test"]
    
    frame_times = []
    max_particles_reached = 0
    
    running = True
    while running:
        start_time = time.time()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    test_mode = (test_mode + 1) % len(test_modes)
                    particle_system.clear()
                    frame_times.clear()
                    max_particles_reached = 0
                elif event.key == pygame.K_c:
                    particle_system.clear()
                    frame_times.clear()
                    max_particles_reached = 0
        
        dt = clock.tick(60) / 1000.0
        
        # Test different scenarios
        if test_mode == 0:  # Burst test
            if pygame.time.get_ticks() % 500 < 50:  # Every 500ms
                particle_system.add_burst(
                    (400, 300), count=200,
                    speed_range=(50, 150),
                    life_range=(1.0, 3.0),
                    size_range=(1, 6),
                    color=(255, 100, 50, 200)
                )
        
        elif test_mode == 1:  # Continuous test
            # Add particles continuously
            for _ in range(50):
                particle_system.add_particle(
                    (400 + math.sin(pygame.time.get_ticks() * 0.01) * 100,
                     300 + math.cos(pygame.time.get_ticks() * 0.01) * 100),
                    ((random.random() - 0.5) * 100,
                     (random.random() - 0.5) * 100),
                    (0, 20),
                    random.random() * 2 + 1,
                    random.randint(1, 5),
                    (255, 255, 255, 200)
                )
        
        elif test_mode == 2:  # Racing effects test
            t = pygame.time.get_ticks() * 0.001
            car_x = 400 + math.sin(t) * 200
            car_y = 300 + math.cos(t) * 150
            car_vx = math.cos(t) * 100
            car_vy = -math.sin(t) * 100
            car_angle = math.atan2(car_vy, car_vx)
            
            # Simulate racing effects
            racing_effects.exhaust_smoke((car_x, car_y), (car_vx, car_vy), car_angle, 1.0)
            
            if int(t) % 3 == 0:  # Occasional drift
                tire_positions = [(car_x - 10, car_y + 15), (car_x + 10, car_y + 15)]
                racing_effects.tire_smoke_drift(tire_positions, 0.8)
            
            if int(t) % 5 == 0:  # Occasional sparks
                racing_effects.sparks_collision((car_x, car_y), car_angle, 0.5)
        
        # Update systems
        particle_system.update(dt, camera)
        
        # Track statistics
        stats = particle_system.get_performance_stats()
        max_particles_reached = max(max_particles_reached, stats['active_particles'])
        
        # Render
        screen.fill((20, 20, 40))
        
        # Render particles
        particle_surface = particle_system.render(camera)
        screen.blit(particle_surface, (0, 0), special_flags=pygame.BLEND_ALPHA_SDL2)
        
        # Draw performance info
        fps = clock.get_fps()
        frame_times.append(1000.0 / max(fps, 1))  # Frame time in ms
        
        if len(frame_times) > 60:
            frame_times.pop(0)
        
        avg_frame_time = sum(frame_times) / len(frame_times)
        
        info_lines = [
            f"Test Mode: {test_modes[test_mode]} (SPACE to change)",
            f"FPS: {fps:.1f} (Avg Frame Time: {avg_frame_time:.2f}ms)",
            f"Active Particles: {stats['active_particles']}",
            f"Max Particles Reached: {max_particles_reached}",
            f"Pooled Particles: {stats['pooled_particles']}",
            f"Memory Usage: {stats['memory_usage_mb']:.2f} MB",
            "",
            "C: Clear particles",
            "ESC: Exit"
        ]
        
        for i, line in enumerate(info_lines):
            color = (255, 255, 255) if not line.startswith("FPS:") else (255, 255, 0) if fps > 50 else (255, 100, 100)
            text = font.render(line, True, color)
            screen.blit(text, (10, 10 + i * 25))
        
        # Performance warning
        if fps < 30:
            warning = font.render("WARNING: Low FPS! Consider reducing particle count", True, (255, 0, 0))
            screen.blit(warning, (10, screen.get_height() - 30))
        
        # Draw test visualization
        if test_mode == 2:  # Show car in racing test
            t = pygame.time.get_ticks() * 0.001
            car_x = 400 + math.sin(t) * 200
            car_y = 300 + math.cos(t) * 150
            car_angle = math.atan2(-math.sin(t) * 100, math.cos(t) * 100)
            
            # Simple car representation
            car_points = [
                (car_x + 15 * math.cos(car_angle), car_y + 15 * math.sin(car_angle)),
                (car_x - 15 * math.cos(car_angle), car_y - 15 * math.sin(car_angle)),
                (car_x - 10 * math.cos(car_angle) - 8 * math.sin(car_angle), 
                 car_y - 10 * math.sin(car_angle) + 8 * math.cos(car_angle)),
                (car_x - 10 * math.cos(car_angle) + 8 * math.sin(car_angle), 
                 car_y - 10 * math.sin(car_angle) - 8 * math.cos(car_angle))
            ]
            pygame.draw.polygon(screen, (100, 150, 255), car_points)
        
        pygame.display.flip()
        
        # Calculate actual frame time
        frame_time = time.time() - start_time
        
        # Exit on ESC
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            running = False
    
    # Print final performance report
    print("\n=== PARTICLE SYSTEM PERFORMANCE REPORT ===")
    print(f"Test completed")
    print(f"Max particles reached: {max_particles_reached}")
    print(f"Average frame time: {avg_frame_time:.2f}ms")
    print(f"Final FPS: {fps:.1f}")
    print(f"Memory usage: {stats['memory_usage_mb']:.2f} MB")
    
    if avg_frame_time < 16.67:  # 60 FPS
        print("✓ EXCELLENT: Maintains 60+ FPS")
    elif avg_frame_time < 33.33:  # 30 FPS
        print("✓ GOOD: Maintains 30+ FPS")
    else:
        print("⚠ WARNING: Performance below 30 FPS")
    
    pygame.quit()


if __name__ == "__main__":
    print("Starting particle system performance test...")
    print("Controls:")
    print("  SPACE: Change test mode")
    print("  C: Clear particles")
    print("  ESC: Exit")
    print("\nTest modes:")
    print("  1. Burst Test: Periodic particle bursts")
    print("  2. Continuous Test: Steady particle emission")
    print("  3. Racing Effects Test: Realistic racing particle effects")
    print("\nStarting test...")
    
    try:
        test_particle_performance()
    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()