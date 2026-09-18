#!/usr/bin/env python3
from pathlib import Path
import sys

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILLS_ROOT / "loader"))

from generic_skill_runtime import main

if __name__ == "__main__":
    raise SystemExit(main(SKILL_DIR))
