"""Local, read-only Qlik export analysis. No Qlik or AWS connection is made."""
import sys
from pathlib import Path

deps = Path(__file__).resolve().parent.parent / '.deps'
if deps.is_dir():
    sys.path.insert(0, str(deps))
