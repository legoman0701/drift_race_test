import pygame

def blur_surface(surface, world_size, scale_factor=0.1):
    scaled_size = (max(1, int(world_size[0] * scale_factor)), max(1, int(world_size[1] * scale_factor)))
    small_surface = pygame.transform.smoothscale(surface, scaled_size) # scale down the surface
    blurred_surface = pygame.transform.smoothscale(small_surface, world_size) # scale back to original size
    return blurred_surface