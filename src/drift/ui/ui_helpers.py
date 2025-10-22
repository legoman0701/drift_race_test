import pygame

def blur_surface(surface, world_size, scale_factor=0.1):
    scaled_size = (max(1, int(world_size[0] * scale_factor)), max(1, int(world_size[1] * scale_factor)))
    small_surface = pygame.transform.smoothscale(surface, scaled_size) # scale down the surface
    blurred_surface = pygame.transform.smoothscale(small_surface, world_size) # scale back to original size
    return blurred_surface

# ======= TEXT RENDERING CACHE FOR HEADER/FOOTER =======
# Pre-rendered text surfaces to avoid expensive font.render() calls every frame
_header_footer_text_cache = {}

def get_cached_text(font, text, color, cache_key=None):
    """Get or create cached text surface for header/footer elements.
    
    Args:
        font: pygame.Font object
        text: Text string to render
        color: RGB tuple for text color
        cache_key: Optional custom cache key (if None, auto-generates from params)
    
    Returns:
        Pre-rendered pygame.Surface with the text
    """
    if cache_key is None:
        cache_key = (id(font), text, color)
    
    if cache_key not in _header_footer_text_cache:
        _header_footer_text_cache[cache_key] = font.render(text, True, color)
    
    return _header_footer_text_cache[cache_key]

def invalidate_ui_text_cache(cache_type=None):
    """Clear specific parts of header/footer text cache.
    
    Args:
        cache_type: What to invalidate:
            - None or 'all': Clear everything (default for safety)
            - 'debug': Only debug status text
            - 'room': Only room code text
            - 'host': Only host username text
            - 'title': Only page title text
    """
    global _header_footer_text_cache
    
    if cache_type is None or cache_type == 'all':
        _header_footer_text_cache.clear()
        return
    
    # Selective invalidation: remove only keys matching the type
    keys_to_remove = []
    for key in _header_footer_text_cache.keys():
        # Keys are tuples like (font_id, text, color) or custom tuples
        # Check if the key contains our cache_type identifier
        if isinstance(key, tuple) and len(key) >= 2:
            if cache_type == 'debug' and 'debug' in str(key).lower():
                keys_to_remove.append(key)
            elif cache_type == 'room' and 'room' in str(key).lower():
                keys_to_remove.append(key)
            elif cache_type == 'host' and 'host' in str(key).lower():
                keys_to_remove.append(key)
            elif cache_type == 'title' and isinstance(key[1], str):
                # Title keys are like (font_id, "Lobby", color)
                # Remove if it's a known title string
                if key[1] in ["Lobby", "In Game", "Settings", "Host Game", "Join Game", "Error"]:
                    keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del _header_footer_text_cache[key]