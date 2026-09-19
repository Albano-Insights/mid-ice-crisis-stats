"""Append ?v=<content hash> to the stylesheet/script links in docs/*.html so a changed asset is
never served from a stale cache (GitHub Pages caches for 10 minutes; browsers longer)."""
import hashlib
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
ASSETS = ("styles.css", "v2.css", "app.js", "app2.js")


def stamp(text: str) -> str:
    for asset in ASSETS:
        f = DOCS / asset
        if not f.exists():
            continue
        v = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
        pattern = re.compile(r'(?P<attr>href|src)="' + re.escape(asset) + r'(\?v=[0-9a-f]+)?"')
        text = pattern.sub(lambda m: f'{m.group("attr")}="{asset}?v={v}"', text)
    return text


if __name__ == "__main__":
    for html in DOCS.glob("*.html"):
        html.write_text(stamp(html.read_text(encoding="utf-8")), encoding="utf-8")
    print("stamped")
