"""
Specialized particle effects for drift racing game.
This module provides pre-configured effect functions for common racing scenarios.
"""

import pygame
import math
import random
from typing import Tuple
from .particles import ParticleSystem


class RacingParticleEffects:
    """
    Collection of pre-configured particle effects for racing games.
    """
    
    def __init__(self, particle_system: ParticleSystem):
        self.particle_system = particle_system
    
    def exhaust_smoke(self, pos: Tuple[float, float], velocity: Tuple[float, float], 
                     car_angle: float, intensity: float = 1.0, engine_temp: float = 1.0):
        """
        Create realistic exhaust smoke based on car parameters.
        
        Args:
            pos: Car position (x, y)
            velocity: Car velocity (vx, vy)
            car_angle: Car rotation in radians
            intensity: How much exhaust (0.0 to 2.0)
            engine_temp: Engine temperature factor (affects color)
        """
        if intensity <= 0:
            return
        
        # Calculate exhaust pipe position (behind the car)
        exhaust_offset_x = -25 * math.cos(car_angle)  # Behind car
        exhaust_offset_y = -25 * math.sin(car_angle)
        
        exhaust_pos = (pos[0] + exhaust_offset_x, pos[1] + exhaust_offset_y)
        
        # Number of particles based on intensity and speed
        speed = math.sqrt(velocity[0]**2 + velocity[1]**2)
        particle_count = max(1, int(intensity * (1 + speed * 0.02)))
        particle_count = min(particle_count, 15)  # Performance cap
        
        for _ in range(particle_count):
            # Exhaust direction with spread
            base_angle = car_angle + math.pi + random.uniform(-0.3, 0.3)
            exhaust_speed = random.uniform(30, 80) * intensity
            
            vel = (math.cos(base_angle) * exhaust_speed + random.uniform(-20, 20),
                   math.sin(base_angle) * exhaust_speed + random.uniform(-20, 20))
            
            # Position spread
            particle_pos = (exhaust_pos[0] + random.uniform(-5, 5),
                           exhaust_pos[1] + random.uniform(-5, 5))
            
            # Color based on engine temperature
            if engine_temp > 1.5:  # Hot engine - darker smoke
                gray = random.randint(40, 80)
            else:  # Normal engine - lighter smoke
                gray = random.randint(80, 140)
            
            alpha = random.randint(60, 120)
            
            self.particle_system.add_particle(
                particle_pos, vel,
                (0, 15),  # slight downward acceleration
                random.uniform(0.8, 2.2),  # life
                random.randint(3, 6),  # size
                (gray, gray, gray, alpha)
            )
    
    def tire_smoke_drift(self, tire_positions: list, drift_intensity: float, 
                        surface_type: str = "asphalt"):
        """
        Create tire smoke for drifting based on tire positions and surface.
        
        Args:
            tire_positions: List of (x, y) tuples for tire positions
            drift_intensity: How much the car is drifting (0.0 to 1.0)
            surface_type: "asphalt", "dirt", "grass" affects particle color
        """
        if drift_intensity < 0.3:  # Only create smoke for significant drifting
            return
        
        # Color based on surface type
        if surface_type == "dirt":
            base_color = (139, 69, 19)  # Brown
            color_variance = 40
        elif surface_type == "grass":
            base_color = (34, 139, 34)  # Green
            color_variance = 30
        else:  # asphalt
            base_color = (200, 200, 200)  # Light gray
            color_variance = 50
        
        for tire_pos in tire_positions:
            particle_count = max(1, int(drift_intensity * 20))
            
            for _ in range(particle_count):
                # Random velocity spread
                vel = (random.uniform(-40, 40), random.uniform(-40, 40))
                
                # Position spread around tire
                particle_pos = (tire_pos[0] + random.uniform(-8, 8),
                               tire_pos[1] + random.uniform(-8, 8))
                
                # Color with variance
                r = max(0, min(255, base_color[0] + random.randint(-color_variance, color_variance)))
                g = max(0, min(255, base_color[1] + random.randint(-color_variance, color_variance)))
                b = max(0, min(255, base_color[2] + random.randint(-color_variance, color_variance)))
                alpha = random.randint(80, 160)
                
                # Acceleration based on surface (dust/smoke behavior)
                if surface_type == "dirt":
                    acc = (random.uniform(-10, 10), random.uniform(-30, -10))  # Dust settles
                else:
                    acc = (0, random.uniform(-5, 5))  # Smoke drifts
                
                self.particle_system.add_particle(
                    particle_pos, vel, acc,
                    random.uniform(1.0, 3.0),  # longer life for drift smoke
                    random.randint(4, 8),  # larger particles
                    (r, g, b, alpha)
                )
    
    def sparks_collision(self, pos: Tuple[float, float], collision_angle: float, intensity: float = 1.0):
        """
        Create sparks for car collisions or scraping.
        
        Args:
            pos: Collision point (x, y)
            collision_angle: Direction of collision in radians
            intensity: Collision intensity (0.0 to 2.0)
        """
        particle_count = max(5, int(intensity * 30))
        particle_count = min(particle_count, 50)
        
        for _ in range(particle_count):
            # Sparks fly in hemisphere away from collision
            spark_angle = collision_angle + random.uniform(-math.pi/2, math.pi/2)
            spark_speed = random.uniform(50, 200) * intensity
            
            vel = (math.cos(spark_angle) * spark_speed,
                   math.sin(spark_angle) * spark_speed)
            
            # Position spread
            particle_pos = (pos[0] + random.uniform(-3, 3),
                           pos[1] + random.uniform(-3, 3))
            
            # Spark colors (yellow to orange to red)
            color_choice = random.choice([
                (255, 255, 100, 255),  # Bright yellow
                (255, 200, 50, 255),   # Orange
                (255, 100, 50, 255),   # Red-orange
                (255, 255, 255, 255),  # White hot
            ])
            
            self.particle_system.add_particle(
                particle_pos, vel,
                (0, 200),  # gravity pulls sparks down
                random.uniform(0.1, 0.8),  # short life
                random.randint(1, 3),  # small particles
                color_choice
            )
    
    def dust_cloud(self, pos: Tuple[float, float], size: float = 1.0, surface_type: str = "dirt"):
        """
        Create a dust cloud for off-road driving or impacts.
        
        Args:
            pos: Center of dust cloud (x, y)
            size: Size multiplier
            surface_type: "dirt", "sand", "gravel"
        """
        # Color based on surface
        if surface_type == "sand":
            base_color = (238, 203, 173)  # Sandy brown
        elif surface_type == "gravel":
            base_color = (128, 128, 128)  # Gray
        else:  # dirt
            base_color = (139, 69, 19)   # Brown
        
        particle_count = max(10, int(size * 40))
        
        for _ in range(particle_count):
            # Circular spread
            angle = random.uniform(0, 2 * math.pi)
            distance = random.uniform(0, 30 * size)
            
            particle_pos = (pos[0] + math.cos(angle) * distance,
                           pos[1] + math.sin(angle) * distance)
            
            # Outward velocity
            vel = (math.cos(angle) * random.uniform(10, 50),
                   math.sin(angle) * random.uniform(10, 50))
            
            # Color variation
            r = max(0, min(255, base_color[0] + random.randint(-30, 30)))
            g = max(0, min(255, base_color[1] + random.randint(-30, 30)))
            b = max(0, min(255, base_color[2] + random.randint(-30, 30)))
            alpha = random.randint(100, 200)
            
            self.particle_system.add_particle(
                particle_pos, vel,
                (0, -20),  # dust settles down
                random.uniform(2.0, 4.0),  # longer life for dust
                random.randint(3, 7),
                (r, g, b, alpha)
            )
    
    def nitrous_flame(self, pos: Tuple[float, float], car_angle: float, intensity: float = 1.0):
        """
        Create blue flame effect for nitrous boost.
        
        Args:
            pos: Car position (x, y)
            car_angle: Car rotation in radians
            intensity: Nitrous intensity (0.0 to 1.0)
        """
        if intensity <= 0:
            return
        
        # Flame comes from exhaust pipe
        flame_offset_x = -30 * math.cos(car_angle)
        flame_offset_y = -30 * math.sin(car_angle)
        
        flame_pos = (pos[0] + flame_offset_x, pos[1] + flame_offset_y)
        
        particle_count = max(3, int(intensity * 15))
        
        for _ in range(particle_count):
            # Flame direction (behind car with slight spread)
            flame_angle = car_angle + math.pi + random.uniform(-0.2, 0.2)
            flame_speed = random.uniform(60, 120) * intensity
            
            vel = (math.cos(flame_angle) * flame_speed,
                   math.sin(flame_angle) * flame_speed)
            
            # Position spread
            particle_pos = (flame_pos[0] + random.uniform(-3, 3),
                           flame_pos[1] + random.uniform(-3, 3))
            
            # Blue flame colors
            color_choice = random.choice([
                (100, 150, 255, 200),  # Light blue
                (50, 100, 255, 200),   # Blue
                (150, 200, 255, 200),  # Very light blue
                (0, 100, 255, 200),    # Deep blue
            ])
            
            self.particle_system.add_particle(
                particle_pos, vel,
                (0, 10),  # slight acceleration
                random.uniform(0.2, 0.6),  # short life for flame
                random.randint(2, 5),
                color_choice
            )
    
    def water_splash(self, pos: Tuple[float, float], velocity: Tuple[float, float], size: float = 1.0):
        """
        Create water splash effect for driving through puddles.
        
        Args:
            pos: Splash center (x, y)
            velocity: Direction and speed of splash (vx, vy)
            size: Size multiplier
        """
        particle_count = max(5, int(size * 25))
        
        # Base splash direction
        base_angle = math.atan2(velocity[1], velocity[0])
        speed = math.sqrt(velocity[0]**2 + velocity[1]**2)
        
        for _ in range(particle_count):
            # Splash spread
            splash_angle = base_angle + random.uniform(-math.pi/3, math.pi/3)
            splash_speed = random.uniform(20, 80) + speed * 0.3
            
            vel = (math.cos(splash_angle) * splash_speed,
                   math.sin(splash_angle) * splash_speed)
            
            # Position spread
            particle_pos = (pos[0] + random.uniform(-10 * size, 10 * size),
                           pos[1] + random.uniform(-10 * size, 10 * size))
            
            # Water colors (blue with transparency)
            blue_value = random.randint(150, 255)
            alpha = random.randint(80, 150)
            
            self.particle_system.add_particle(
                particle_pos, vel,
                (0, 100),  # gravity pulls water down
                random.uniform(0.5, 1.5),
                random.randint(2, 5),
                (50, 150, blue_value, alpha)
            )


# Usage example:
"""
# In your game initialization:
particle_system = ParticleSystem(max_particles=8000)
racing_effects = RacingParticleEffects(particle_system)

# In your game loop:
# Exhaust smoke when car is moving
if car_speed > 30:
    racing_effects.exhaust_smoke(
        car.x, car.y, car.vx, car.vy, 
        car.angle, intensity=car_speed/200, 
        engine_temp=car.engine_temperature
    )

# Tire smoke when drifting
if car.is_drifting:
    racing_effects.tire_smoke_drift(
        car.tire_positions, car.drift_intensity, 
        surface_type="asphalt"
    )

# Sparks on collision
if collision_detected:
    racing_effects.sparks_collision(
        collision_point.x, collision_point.y,
        collision_angle, collision_force
    )

# Nitrous effect
if car.nitrous_active:
    racing_effects.nitrous_flame(
        car.x, car.y, car.angle, 
        intensity=car.nitrous_level
    )
"""