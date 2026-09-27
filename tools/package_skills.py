#!/usr/bin/env python3
"""Build one installable .skill file (a zip) per folder in skills/.

    python tools/package_skills.py --out dist
"""
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = {".pyc"}


def build(skill: Path, out: Path) -> Path:
    if not (skill / "SKILL.md").exists():
        raise SystemExit(f"{skill} has no SKILL.md")
    target = out / f"{skill.name}.skill"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(skill.rglob("*")):
            if f.is_dir() or SKIP_DIRS & set(f.parts) or f.suffix in SKIP_SUFFIX:
                continue
            z.write(f, Path(skill.name) / f.relative_to(skill))
    return target


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    a = ap.parse_args()
    out = ROOT / a.out if not Path(a.out).is_absolute() else Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for skill in sorted((ROOT / "skills").iterdir()):
        if skill.is_dir():
            print(build(skill, out))


if __name__ == "__main__":
    main()
