"""GROOPS executable: the existing build is reused (confirmed 2026-10-10); this package does not build GROOPS.

Default: ~/groops_build/groops_install/bin/groops (built by the previous pipeline from release 2025-11-15).
Another executable can be given with --groops-bin.
"""
import os
import shutil
import sys

from core import settings


def get_groops(groops_bin=None):
    exe = str(groops_bin) if groops_bin else str(settings.GROOPS_EXE)
    if os.path.isfile(exe) and os.access(exe, os.X_OK):
        return exe
    if groops_bin and shutil.which(exe):
        return shutil.which(exe)
    sys.exit(f"[groops] GROOPS executable not found: {exe}\n"
             f"  The pipeline reuses your existing build (release {settings.GROOPS_TAG}). "
             f"Give its path with --groops-bin /path/to/groops")
