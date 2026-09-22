#!/usr/bin/env python3
"""Compatibility entry point. Uses the maintained CLI without source patching.

Paths retain the caller working-directory semantics. Unicode image I/O and
checked output writes are handled by rock_gradation.py itself.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rock_gradation import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
