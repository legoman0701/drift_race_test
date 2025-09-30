# Runtime hook to set CWD to the executable directory at startup.
# This helps when the game loads assets using relative paths like 'assets/...'.
import os, sys

if hasattr(sys, '_MEIPASS'):
    # When running from a PyInstaller one-file bundle, resources are extracted to _MEIPASS.
    os.chdir(sys._MEIPASS)
else:
    # When running from source or one-folder build, use the directory of the executable/script.
    exe_dir = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])
    if exe_dir:
        os.chdir(exe_dir)
