"""
Highly optimized particle system for drift racing game.
Designed for maximum performance with viewport culling and minimal memory allocations.
"""

import pygame
import numpy as np
from typing import List, Tuple, Optional, Union
import math


class Particle:
    """Single particle with minimal memory footprint using __slots__."""
    __slots__ = ('pos', 'vel', 'acc', 'life', 'age', 'size', 'color')
    
    def __init__(self, pos: Tuple[float, float], vel: Tuple[float, float] = (0.0, 0.0),
                 acc: Tuple[float, float] = (0.0, 0.0), life: float = 1.0,
                 size: int = 1, color: Tuple[int, int, int, int] = (255, 255, 255, 255)):
        self.pos = pos      # (x, y)
        self.vel = vel      # (vx, vy)
        self.acc = acc      # (ax, ay)
        self.life = life
        self.age = 0.0
        self.size = max(1, min(8, size))  # Clamp between 1-8
        self.color = color  # (r, g, b, a)
    
    @property
    def x(self) -> float:
        return self.pos[0]
    
    @property
    def y(self) -> float:
        return self.pos[1]
    
    @property
    def vx(self) -> float:
        return self.vel[0]
    
    @property
    def vy(self) -> float:
        return self.vel[1]
    
    @property
    def ax(self) -> float:
        return self.acc[0]
    
    @property
    def ay(self) -> float:
        return self.acc[1]


class ParticleSystem:
    """
    Highly optimized particle system with viewport culling and batch operations.
    Uses object pooling and numpy for maximum performance.
    """
    
    def __init__(self, max_particles: int = 10000):
        self.max_particles = max_particles
        self.particles: List[Particle] = []
        self.dead_particles: List[Particle] = []  # Object pool for reuse
        
        # Pre-allocated surfaces for different particle sizes (1x1 to 8x8)
        self._particle_surfaces = {}
        for size in range(1, 9):
            self._particle_surfaces[size] = pygame.Surface((size, size), pygame.SRCALPHA)
        
        # Batch processing arrays for numpy operations
        self._batch_size = 1000
        self._pos_array = np.zeros((self._batch_size, 2), dtype=np.float32)
        self._vel_array = np.zeros((self._batch_size, 2), dtype=np.float32)
        self._acc_array = np.zeros((self._batch_size, 2), dtype=np.float32)
        
        # Viewport culling margins (particles slightly outside view are still updated)
        self._cull_margin = 50
        
        # Frame counter for optimization
        self._frame_count = 0

    def add_particle(self, pos: Tuple[float, float], vel: Tuple[float, float] = (0.0, 0.0),
                    acc: Tuple[float, float] = (0.0, 0.0), life: float = 1.0,
                    size: int = 1, color: Tuple[int, int, int, int] = (255, 255, 255, 255)) -> bool:
        """
        Add a new particle to the system.
        Returns True if particle was added, False if system is at capacity.
        """
        if len(self.particles) >= self.max_particles:
            return False
        
        # Try to reuse a dead particle first (object pooling)
        if self.dead_particles:
            particle = self.dead_particles.pop()
            particle.pos = pos
            particle.vel = vel
            particle.acc = acc
            particle.life = life
            particle.age = 0.0
            particle.size = max(1, min(8, size))
            particle.color = color
        else:
            particle = Particle(pos, vel, acc, life, size, color)
        
        self.particles.append(particle)
        return True

    def add_burst(self, pos: Tuple[float, float], count: int, speed_range: Tuple[float, float] = (10, 50),
                  angle_range: Tuple[float, float] = (0, 360), life_range: Tuple[float, float] = (0.5, 2.0),
                  size_range: Tuple[int, int] = (1, 4), color: Tuple[int, int, int, int] = (255, 255, 255, 255)) -> int:
        """
        Add a burst of particles at once for explosion/exhaust effects.
        Returns number of particles actually added.
        """
        added = 0
        for _ in range(count):
            if len(self.particles) >= self.max_particles:
                break
            
            # Random angle and speed
            angle = math.radians(np.random.uniform(angle_range[0], angle_range[1]))
            speed = np.random.uniform(speed_range[0], speed_range[1])
            
            vel = (math.cos(angle) * speed, math.sin(angle) * speed)
            
            # Random properties
            life = np.random.uniform(life_range[0], life_range[1])
            size = np.random.randint(size_range[0], size_range[1] + 1)
            
            if self.add_particle(pos, vel, (0, 0), life, size, color):
                added += 1
        
        return added

    def update(self, dt: float, cam, world_size: Tuple[int, int] = None) -> None:
        """
        Update all particles with optimized batch processing and viewport culling.
        """
        if not self.particles:
            return
        
        self._frame_count += 1
        
        # Calculate viewport bounds for culling
        view_left = cam.x - (cam.width / 2) / cam.zoom - self._cull_margin
        view_right = cam.x + (cam.width / 2) / cam.zoom + self._cull_margin
        view_top = cam.y - (cam.height / 2) / cam.zoom - self._cull_margin
        view_bottom = cam.y + (cam.height / 2) / cam.zoom + self._cull_margin
        
        # Process particles in batches for better cache performance
        alive_particles = []
        batch_start = 0
        
        while batch_start < len(self.particles):
            batch_end = min(batch_start + self._batch_size, len(self.particles))
            batch_particles = self.particles[batch_start:batch_end]
            
            # Process this batch
            for particle in batch_particles:
                # Update age
                particle.age += dt
                
                # Check if particle is dead
                if particle.age >= particle.life:
                    self.dead_particles.append(particle)  # Return to pool
                    continue
                
                # Update physics
                new_vx = particle.vx + particle.ax * dt
                new_vy = particle.vy + particle.ay * dt
                particle.vel = (new_vx, new_vy)
                
                new_x = particle.x + new_vx * dt
                new_y = particle.y + new_vy * dt
                particle.pos = (new_x, new_y)
                
                # Viewport culling - only keep particles that might be visible
                if (view_left <= particle.x <= view_right and 
                    view_top <= particle.y <= view_bottom):
                    alive_particles.append(particle)
                elif particle.life - particle.age > 1.0:  # Keep long-lived particles even if outside view
                    alive_particles.append(particle)
                else:
                    # Particle is outside view and dying soon, remove it
                    self.dead_particles.append(particle)
            
            batch_start = batch_end
        
        self.particles = alive_particles

    def render(self, cam, target_surface: pygame.Surface = None) -> pygame.Surface:
        """
        Render particles to a surface the size of the camera view.
        Performs screen-space culling and optimized drawing.
        """
        if not self.particles:
            if target_surface:
                target_surface.fill((0, 0, 0, 0))
                return target_surface
            else:
                surface = pygame.Surface((cam.width, cam.height), pygame.SRCALPHA)
                surface.fill((0, 0, 0, 0))
                return surface
        
        # Create or use provided surface
        if target_surface is None:
            surface = pygame.Surface((cam.width, cam.height), pygame.SRCALPHA)
        else:
            surface = target_surface
        
        surface.fill((0, 0, 0, 0))  # Clear with transparent
        
        # Calculate view bounds in world coordinates
        view_left = cam.x - (cam.width / 2) / cam.zoom
        view_right = cam.x + (cam.width / 2) / cam.zoom
        view_top = cam.y - (cam.height / 2) / cam.zoom
        view_bottom = cam.y + (cam.height / 2) / cam.zoom
        
        # Group particles by size for batch rendering
        particles_by_size = {}
        
        for particle in self.particles:
            # Screen space culling - only render visible particles
            if not (view_left <= particle.x <= view_right and 
                   view_top <= particle.y <= view_bottom):
                continue
            
            # Convert world coordinates to screen coordinates
            screen_x = (particle.x - view_left) * cam.zoom
            screen_y = (particle.y - view_top) * cam.zoom
            
            # Skip particles that are definitely off-screen after zoom
            if (screen_x < -particle.size or screen_x > cam.width + particle.size or
                screen_y < -particle.size or screen_y > cam.height + particle.size):
                continue
            
            # Group by size for batch processing
            if particle.size not in particles_by_size:
                particles_by_size[particle.size] = []
            
            # Calculate alpha based on age
            alpha = max(0, min(255, int(particle.color[3] * (1.0 - particle.age / particle.life))))
            
            particles_by_size[particle.size].append({
                'x': int(screen_x),
                'y': int(screen_y), 
                'r': particle.color[0],
                'g': particle.color[1],
                'b': particle.color[2],
                'a': alpha
            })
        
        # Render particles grouped by size for better performance
        for size, size_particles in particles_by_size.items():
            if size == 1:
                # Optimize 1x1 pixels - draw directly
                for p in size_particles:
                    if 0 <= p['x'] < cam.width and 0 <= p['y'] < cam.height:
                        if p['a'] > 0:
                            color = (p['r'], p['g'], p['b'], p['a'])
                            surface.set_at((p['x'], p['y']), color)
            else:
                # Use pre-allocated surfaces for larger particles
                particle_surf = self._particle_surfaces[size]
                
                for p in size_particles:
                    if p['a'] > 0:
                        # Fill the particle surface with the color
                        particle_surf.fill((p['r'], p['g'], p['b'], p['a']))
                        
                        # Blit to main surface
                        surface.blit(particle_surf, (p['x'] - size//2, p['y'] - size//2))
        
        return surface
    
    def render_world(self, world_surface: pygame.Surface, viewport: Optional[Tuple[float, float, float, float]] = None):
        """
        Render particles directly to a world-coordinate surface.
        Particles are positioned at their world coordinates.
        
        Args:
            world_surface: The surface to render particles on (in world coordinates)
            viewport: Optional (x, y, width, height) viewport for culling. If None, renders all particles.
        """
        if not self.particles:
            return
        
        # Viewport culling bounds
        if viewport:
            view_left, view_top, view_width, view_height = viewport
            view_right = view_left + view_width
            view_bottom = view_top + view_height
            cull = True
        else:
            cull = False
        
        # Group particles by size for batch rendering
        particles_by_size = {}
        
        for particle in self.particles:
            # Viewport culling if enabled
            if cull and not (view_left <= particle.x <= view_right and 
                           view_top <= particle.y <= view_bottom):
                continue
            
            # Group by size
            if particle.size not in particles_by_size:
                particles_by_size[particle.size] = []
            
            # Calculate alpha fade based on age
            alpha = max(0, min(255, int(particle.color[3] * (1.0 - particle.age / particle.life))))
            
            particles_by_size[particle.size].append({
                'x': int(particle.x),
                'y': int(particle.y),
                'r': particle.color[0],
                'g': particle.color[1],
                'b': particle.color[2],
                'a': alpha
            })
        
        # Render particles grouped by size
        for size, size_particles in particles_by_size.items():
            if size == 1:
                # Optimize 1x1 pixels - draw directly
                for p in size_particles:
                    if p['a'] > 0:
                        try:
                            world_surface.set_at((p['x'], p['y']), (p['r'], p['g'], p['b'], p['a']))
                        except IndexError:
                            pass  # Skip out-of-bounds particles
            else:
                # Use pre-allocated surfaces for larger particles
                particle_surf = self._particle_surfaces[size]
                
                for p in size_particles:
                    if p['a'] > 0:
                        # Fill the particle surface with the color
                        particle_surf.fill((p['r'], p['g'], p['b'], p['a']))
                        
                        # Blit to world surface
                        world_surface.blit(particle_surf, (p['x'] - size//2, p['y'] - size//2))

    def add_exhaust_effect(self, pos: Tuple[float, float], velocity: Tuple[float, float], 
                          intensity: float = 1.0) -> None:
        """
        Add exhaust particles based on car velocity and position.
        Optimized for car exhaust effects.
        """
        # Calculate exhaust direction (opposite to velocity)
        speed = math.sqrt(velocity[0]**2 + velocity[1]**2)
        if speed > 0:
            # Normalize velocity and create exhaust direction
            norm_vx = -velocity[0] / speed
            norm_vy = -velocity[1] / speed
        else:
            norm_vx = 0
            norm_vy = 0
        
        # Number of particles based on intensity and speed
        particle_count = max(1, int(intensity * speed * 0.1))
        particle_count = min(particle_count, 20)  # Cap for performance
        
        for _ in range(particle_count):
            # Random spread around exhaust direction
            spread_angle = np.random.uniform(-0.5, 0.5)
            cos_spread = math.cos(spread_angle)
            sin_spread = math.sin(spread_angle)
            
            exhaust_vx = (norm_vx * cos_spread - norm_vy * sin_spread) * np.random.uniform(20, 80)
            exhaust_vy = (norm_vx * sin_spread + norm_vy * cos_spread) * np.random.uniform(20, 80)
            
            # Random position offset
            offset_x = np.random.uniform(-5, 5)
            offset_y = np.random.uniform(-5, 5)
            
            # Exhaust particles: gray/black smoke
            gray_value = np.random.randint(60, 120)
            alpha = np.random.randint(100, 200)
            
            self.add_particle(
                (pos[0] + offset_x, pos[1] + offset_y),
                (exhaust_vx, exhaust_vy),
                (0, 10),  # slight downward acceleration
                np.random.uniform(0.3, 1.5),  # life
                np.random.randint(2, 6),  # size
                (gray_value, gray_value, gray_value, alpha)
            )

    def add_tire_smoke(self, pos: Tuple[float, float], intensity: float = 1.0) -> None:
        """
        Add tire smoke particles for drifting effects.
        """
        particle_count = max(1, int(intensity * 15))
        
        for _ in range(particle_count):
            # Random velocity spread
            vel = (np.random.uniform(-30, 30), np.random.uniform(-30, 30))
            
            # Random position spread
            offset_x = np.random.uniform(-10, 10)
            offset_y = np.random.uniform(-10, 10)
            
            # White/gray smoke
            gray_value = np.random.randint(180, 255)
            alpha = np.random.randint(80, 150)
            
            self.add_particle(
                (pos[0] + offset_x, pos[1] + offset_y),
                vel,
                (0, -5),  # slight upward acceleration (smoke rises)
                np.random.uniform(0.8, 2.5),  # life
                np.random.randint(3, 7),  # size
                (gray_value, gray_value, gray_value, alpha)
            )

    def clear(self) -> None:
        """Clear all particles and return them to the pool."""
        self.dead_particles.extend(self.particles)
        self.particles.clear()

    def get_particle_count(self) -> int:
        """Get current number of active particles."""
        return len(self.particles)

    def get_performance_stats(self) -> dict:
        """Get performance statistics for debugging."""
        return {
            'active_particles': len(self.particles),
            'pooled_particles': len(self.dead_particles),
            'max_particles': self.max_particles,
            'memory_usage_mb': (len(self.particles) + len(self.dead_particles)) * 64 / 1024 / 1024  # Rough estimate
        }


class ParticleEmitter:
    """
    Utility class for managing continuous particle emission.
    """
    
    def __init__(self, particle_system: ParticleSystem, pos: Tuple[float, float] = (0, 0)):
        self.particle_system = particle_system
        self.pos = pos
        self.enabled = True
        self.emission_rate = 10.0  # particles per second
        self.emission_timer = 0.0
        
        # Default particle properties
        self.velocity_range = (-10, 10, -10, 10)  # min_vx, max_vx, min_vy, max_vy
        self.acceleration = (0, 0)
        self.life_range = (1.0, 2.0)
        self.size_range = (1, 3)
        self.color = (255, 255, 255, 255)

    def update(self, dt: float) -> None:
        """Update the emitter and emit particles based on emission rate."""
        if not self.enabled:
            return
        
        self.emission_timer += dt
        particles_to_emit = int(self.emission_timer * self.emission_rate)
        
        if particles_to_emit > 0:
            self.emission_timer -= particles_to_emit / self.emission_rate
            
            for _ in range(particles_to_emit):
                vel = (np.random.uniform(self.velocity_range[0], self.velocity_range[1]),
                       np.random.uniform(self.velocity_range[2], self.velocity_range[3]))
                life = np.random.uniform(self.life_range[0], self.life_range[1])
                size = np.random.randint(self.size_range[0], self.size_range[1] + 1)
                
                self.particle_system.add_particle(
                    self.pos, vel, 
                    self.acceleration,
                    life, size, 
                    self.color
                )

    def set_position(self, pos: Tuple[float, float]) -> None:
        """Update emitter position."""
        self.pos = pos