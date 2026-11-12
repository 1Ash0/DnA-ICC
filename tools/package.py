"""Build <team>.zip with the required layout:  python tools/package.py"""
import zipfile
from pathlib import Path

TEAM = "45"
ROOT = Path(__file__).resolve().parent.parent
SKIP = {"venv", ".venv", "__pycache__"}
out = ROOT / f"{TEAM}.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for name in (f"{TEAM}.mp4", "phase3.pdf", "README.md"):
        f = ROOT / name
        if f.exists():
            z.write(f, name)
        else:
            print(f"WARNING: {name} missing")
    for f in sorted((ROOT / "src").rglob("*")):
        rel = f.relative_to(ROOT)
        if f.is_file() and not SKIP & set(rel.parts):
            z.write(f, rel.as_posix())
print(f"wrote {out}")
with zipfile.ZipFile(out) as z:
    for n in z.namelist():
        print("  ", n)
