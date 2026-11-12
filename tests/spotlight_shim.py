"""scripts/ is on sys.path for the issue-parser tests; this makes `from lib import spotlight`
resolve the same way build_site_data.py sees it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
