"""
Example usage of the optimized particle system with the drift racing camera.
This file demonstrates how to integrate particles into the existing render pipeline.
"""

import pygame
import sys
import os

# Add the src directory to the path so we can import drift modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from drift.render.particles import ParticleSystem, ParticleEmitter
from drift.render.camera import Camera
import drift.config.const as const


def example_particle_integration():
    """
    Example showing how to integrate the particle system with existing camera and rendering.
    """
    pygame.init()
    
    # Create display
    screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
    pygame.display.set_caption("Optimized Particle System Demo")
    clock = pygame.time.Clock()
    
    # Create camera (same as in your game)
    camera = Camera(const.WINDOW_WIDTH, const.WINDOW_HEIGHT, zoom=1.0)
    
    # Create particle system
    particle_system = ParticleSystem(max_particles=5000)
    
    # Create some emitters for demonstration
    exhaust_emitter = ParticleEmitter(particle_system, (400, 300))
    exhaust_emitter.emission_rate = 50.0
    exhaust_emitter.velocity_range = (-50, 50, -50, 50)
    exhaust_emitter.acceleration = (0, 10)  # gravity
    exhaust_emitter.life_range = (0.5, 2.0)
    exhaust_emitter.size_range = (2, 5)
    exhaust_emitter.color = (100, 100, 100, 200)  # gray smoke
    
    # Simulate car position for camera tracking
    class MockCar:
        def __init__(self):
            self.x = const.WINDOW_WIDTH // 2
            self.y = const.WINDOW_HEIGHT // 2
            self.vx = 0
            self.vy = 0
    
    mock_car = MockCar()
    
    running = True
    mouse_down = False
    
    while running:
        dt = clock.tick(const.FPS) / 1000.0  # Delta time in seconds
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                mouse_down = True
            elif event.type == pygame.MOUSEBUTTONUP:
                mouse_down = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    # Add explosion effect
                    mouse_pos = pygame.mouse.get_pos()
                    world_x = camera.x - (camera.width / 2) / camera.zoom + mouse_pos[0] / camera.zoom
                    world_y = camera.y - (camera.height / 2) / camera.zoom + mouse_pos[1] / camera.zoom
                    
                    particle_system.add_burst(
                        (world_x, world_y), 
                        count=100,
                        speed_range=(50, 200),
                        life_range=(0.5, 3.0),
                        size_range=(1, 6),
                        color=(255, 100, 50, 255)  # Orange explosion
                    )
                elif event.key == pygame.K_c:
                    # Clear all particles
                    particle_system.clear()
        
        # Handle mouse interaction
        if mouse_down:
            mouse_pos = pygame.mouse.get_pos()
            # Convert screen coordinates to world coordinates
            world_x = camera.x - (camera.width / 2) / camera.zoom + mouse_pos[0] / camera.zoom
            world_y = camera.y - (camera.height / 2) / camera.zoom + mouse_pos[1] / camera.zoom
            
            # Add tire smoke effect
            particle_system.add_tire_smoke((world_x, world_y), intensity=1.5)
        
        # Simulate car movement with arrow keys
        keys = pygame.key.get_pressed()
        car_speed = 200  # pixels per second
        if keys[pygame.K_LEFT]:
            mock_car.vx = -car_speed
        elif keys[pygame.K_RIGHT]:
            mock_car.vx = car_speed
        else:
            mock_car.vx *= 0.9  # friction
            
        if keys[pygame.K_UP]:
            mock_car.vy = -car_speed
        elif keys[pygame.K_DOWN]:
            mock_car.vy = car_speed
        else:
            mock_car.vy *= 0.9  # friction
        
        # Update car position
        mock_car.x += mock_car.vx * dt
        mock_car.y += mock_car.vy * dt
        
        # Add exhaust effect if car is moving
        speed = (mock_car.vx**2 + mock_car.vy**2)**0.5
        if speed > 10:
            particle_system.add_exhaust_effect(
                (mock_car.x, mock_car.y),
                (mock_car.vx, mock_car.vy),
                intensity=speed / 100
            )
        
        # Update camera to follow car
        camera.update(mock_car, (1000, 700))
        
        # Update emitters
        exhaust_emitter.set_position((mock_car.x - 20, mock_car.y + 10))  # Behind car
        exhaust_emitter.update(dt)
        
        # Update particle system
        particle_system.update(dt, camera, world_size=(1000, 700))
        
        # Render
        screen.fill(const.GREY_20)  # Dark background
        
        # Render particles - this creates a surface the size of the camera view
        particle_surface = particle_system.render(camera)
        
        # Blit the particle surface to the screen
        screen.blit(particle_surface, (0, 0))
        
        # Draw some UI info
        font = pygame.font.Font(None, 24)
        stats = particle_system.get_performance_stats()
        info_lines = [
            f"Active Particles: {stats['active_particles']}",
            f"Pooled Particles: {stats['pooled_particles']}",
            f"Memory Usage: {stats['memory_usage_mb']:.2f} MB",
            f"FPS: {clock.get_fps():.1f}",
            "",
            "Controls:",
            "Arrow keys: Move car",
            "Mouse drag: Add tire smoke", 
            "Space: Explosion at cursor",
            "C: Clear all particles"
        ]
        
        for i, line in enumerate(info_lines):
            text = font.render(line, True, const.WHITE)
            screen.blit(text, (10, 10 + i * 25))
        
        # Draw mock car
        car_screen_x = int((mock_car.x - camera.x) * camera.zoom + camera.width / 2)
        car_screen_y = int((mock_car.y - camera.y) * camera.zoom + camera.height / 2)
        pygame.draw.rect(screen, const.COLOR_MY_CAR, 
                        (car_screen_x - 10, car_screen_y - 15, 20, 30))
        
        pygame.display.flip()
    
    pygame.quit()


if __name__ == "__main__":
    example_particle_integration()