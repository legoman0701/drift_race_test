#!/usr/bin/env python3
"""
slice_map.py — cut a large map image into ix_iy.png tiles for the chunked renderer.

Defaults match the project layout:
- input  : assets/track/map{x}/main.png
- outdir : assets/track/map{x}/chunks
- tile   : 512 (512x512 tiles)
- indexing: "zero" (top-left tile is 0_0, as the current game uses world coords >= 0)
- prefix : ""  (renderer also accepts "Map1_" as prefix if you prefer)

USAGE EXAMPLES
--------------
# Basic (recommended for your current Map1.png):
python tools/slice_map.py --input assets/track/map1/main.png --outdir assets/track/map1/chunks --tile 512 --indexing zero

# With file prefix (loader supports this too):
python tools/slice_map.py --prefix Map1_

# Centered indexing (origin ~ image center; produces negative/positive indices):
python tools/slice_map.py --indexing center

Notes:
- Edge tiles are padded to the tile size using --pad R,G,B (default 28,28,28).
- A manifest.json is written in the output directory for reference.
"""
import argparse, json, math, os, sys
import drift.config.const as const
from drift.tools.paths import asset_path, normalize_asset_path

# Use pygame for zero-deps in your project (already installed). Pillow is optional.
try:
    import pygame  # pygame or pygame-ce
except Exception as e:
    print("This script requires pygame (or pygame-ce). Please install it (e.g., pip install pygame).")
    raise


def parse_color(s: str):
    parts = [int(p) for p in s.split(",")]
    if len(parts) not in (3, 4):
        raise ValueError("Color must be R,G,B or R,G,B,A")
    if len(parts) == 3:
        parts.append(255)
    return tuple(parts)


def slice_map(
    input_path: str = asset_path("track", f"map{const.MAP_NUM}", "main.png"),
    outdir: str = asset_path("track", f"map{const.MAP_NUM}", "chunks"),
    tile: int = const.TILE_SIZE,
    indexing: str = "zero",
    prefix: str = "",
    pad_color=(28, 28, 28, 255),
    force: bool = False,
):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input image not found: {input_path}")

    os.makedirs(outdir, exist_ok=True)

    # Safety: avoid accidental overwrite if directory isn't empty
    existing = [f for f in os.listdir(outdir) if f.lower().endswith(".png")]
    if existing and not force:
        print(f"[WARN] Output directory '{outdir}' already has {len(existing)} .png files.")
        print("       Re-run with --force to overwrite/append.")
        return

    pygame.init()
    # Load without convert()/convert_alpha() to avoid needing a display surface
    img = pygame.image.load(normalize_asset_path(input_path))
    # If the source has no per-pixel alpha, put it on an SRCALPHA surface so padding blends correctly
    if img.get_alpha() is None:
        tmp = pygame.Surface(img.get_size(), pygame.SRCALPHA)
        tmp.blit(img, (0, 0))
        img = tmp

    W, H = img.get_width(), img.get_height()
    tiles_x = math.ceil(W / tile)
    tiles_y = math.ceil(H / tile)

    if indexing not in ("zero", "center"):
        raise ValueError("--indexing must be 'zero' or 'center'")

    # Determine index ranges
    if indexing == "zero":
        ix_start = 0
        iy_start = 0
    else:
        ix_start = - (tiles_x // 2)
        iy_start = - (tiles_y // 2)

    written = 0
    for ky in range(tiles_y):
        for kx in range(tiles_x):
            ix = ix_start + kx
            iy = iy_start + ky

            # Tile rect in image space
            src_left = kx * tile
            src_top  = ky * tile
            src_right = min(src_left + tile, W)
            src_bot   = min(src_top + tile, H)

            # Create tile surface and fill padding color
            tile_surf = pygame.Surface((tile, tile), pygame.SRCALPHA)
            tile_surf.fill(pad_color)

            # Blit overlap portion (if any)
            if src_right > src_left and src_bot > src_top:
                sub_rect = pygame.Rect(src_left, src_top, src_right - src_left, src_bot - src_top)
                # Destination offset inside the tile (0,0) since we're targeting top-left
                tile_surf.blit(img, (0, 0), area=sub_rect)

            # Save file
            fname = f"{prefix}{ix}_{iy}.png"
            out_path = os.path.join(outdir, fname)
            pygame.image.save(tile_surf, out_path)
            written += 1

    # Manifest for reference
    manifest = {
        "input": str(input_path),  # Convert Path to string for JSON serialization
        "image_size": [W, H],
        "tile": tile,
        "tiles_x": tiles_x,
        "tiles_y": tiles_y,
        "indexing": indexing,
        "ix_start": ix_start,
        "iy_start": iy_start,
        "prefix": prefix,
        "pad_color": list(pad_color),
        "count_written": written,
    }
    manifest_path = os.path.join(str(outdir), "manifest.json")  # Convert outdir to string
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"[OK] Wrote {written} tiles to '{outdir}'. Indexing='{indexing}' (ix_start={ix_start}, iy_start={iy_start})")
    print(f"[OK] Manifest: {manifest_path}")


def main():
    ap = argparse.ArgumentParser(description="Slice a large map PNG into ix_iy.png tiles for the chunked renderer.")
    ap.add_argument("--input", "-i", default=asset_path("track", f"map{const.MAP_NUM}", "main.png"), help="Path to source map image (PNG recommended).")
    ap.add_argument("--outdir", "-o", default=asset_path("track", f"map{const.MAP_NUM}", "chunks"), help="Directory to write tiles into.")
    ap.add_argument("--tile", "-t", type=int, default=const.TILE_SIZE, help="Tile size in pixels (square).")
    ap.add_argument("--indexing", choices=("zero", "center"), default="zero",
                    help="'zero': top-left tile is 0_0; 'center': indices centered near image center (negative/positive).")
    ap.add_argument("--prefix", default="", help="Optional filename prefix, e.g. 'Map1_' produces Map1_ix_iy.png files.")
    ap.add_argument("--pad", default="28,28,28,255",
                    help="Pad color for edge tiles as R,G,B or R,G,B,A. Default 28,28,28,255.")
    ap.add_argument("--force", action="store_true", help="Proceed even if the output directory already contains .png files.")
    args = ap.parse_args()

    try:
        pad_color = parse_color(args.pad)
    except Exception as e:
        print(f"Invalid --pad value: {e}")
        sys.exit(2)

    slice_map(
        input_path=args.input,
        outdir=args.outdir,
        tile=args.tile,
        indexing=args.indexing,
        prefix=args.prefix,
        pad_color=pad_color,
        force=args.force,
    )


if __name__ == "__main__":
    main()
