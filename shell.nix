{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  buildInputs = with pkgs; [
    stdenv.cc.cc.lib
    zlib # Fixes the libz.so.1 error
    freetype # Likely the next thing Pygame will ask for fonts
    libGL
    xorg.libX11
    xorg.libXext
    xorg.libXcursor
    xorg.libXinerama
    xorg.libXi
    xorg.libXrandr
    libxkbcommon
  ];

  shellHook = ''
    # Create the library path from our buildInputs
    export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
      pkgs.stdenv.cc.cc.lib
      pkgs.zlib
      pkgs.freetype
      pkgs.libGL
      pkgs.xorg.libX11
      pkgs.xorg.libXext
      pkgs.xorg.libXcursor
      pkgs.xorg.libXinerama
      pkgs.xorg.libXi
      pkgs.xorg.libXrandr
      pkgs.libxkbcommon
    ]}:$LD_LIBRARY_PATH"

    # Crucial for GPU access on NixOS
    export LD_LIBRARY_PATH="/run/opengl-driver/lib:/run/opengl-driver-32/lib:$LD_LIBRARY_PATH"

    # Skip the broken audio hardware in the lab
    export SDL_AUDIODRIVER=dummy

    echo "🏎️ Environment updated with Font support (libz)!"
  '';
}
