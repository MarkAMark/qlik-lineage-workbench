"""Relocatable entry point for the isolated, bundled Python runtime."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == '__main__':
    from backend.server import main
    main()
