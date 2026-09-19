"""Append ?v=<content hash> to the stylesheet/script links in docs/*.html so a changed asset is
never served from a stale cache (GitHub Pages caches for 10 minutes; browsers longer)."""
import hashlib
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"

for html in DOCS.glob("*.html"):
    text = html.read_text(encoding="utf-8")
    for asset in ("styles.css", "v2.css", "app.js", "app2.js"):
        f = DOCS / asset
        if f.exists():
            v = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
            text = re.sub(rf'(href|src)="{re.escape(asset)}(\?v=[0-9a-f]+)?"', rf'="{asset}?v={v}"', text)
    html.write_text(text, encoding="utf-8")
print("stamped")
