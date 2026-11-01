#!/usr/bin/env python3
"""Complete the internal Aether -> Crows Python package migration.

Run from the repository root on chore/complete-crows-rename:
    python scripts/complete_crows_rename.py
Review the diff, run the full test suite, then commit and push.

Compatibility identifiers (AETHER_* environment fallbacks, X-Aether-Token,
legacy browser storage key, existing database path, and messaging scope) are
intentionally retained. This script only changes Python package references
and implementation-local names.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "aether"
NEW = ROOT / "crows"

REPLACEMENTS = (
    (b"from aether", b"from crows"),
    (b"import aether", b"import crows"),
    (b"aether.app:app", b"crows.app:app"),
    (b'aether*', b'crows*'),
    (b'aether = ["static/*.html"]', b'crows = ["static/*.html"]'),
    (b"COPY aether ./aether", b"COPY crows ./crows"),
    (b"aether_casefold", b"crows_casefold"),
    (b".aether-stage-", b".crows-stage-"),
    (b".aether-rollback-", b".crows-rollback-"),
    (b"aether-iteration-", b"crows-iteration-"),
    (b'"aether.provider"', b'"crows.provider"'),
    (b"'aether.provider'", b"'crows.provider'"),
    (b"`aether/", b"`crows/"),
    (b'"aether/', b'"crows/'),
    (b"'aether/", b"'crows/"),
)

def tracked_files() -> list[Path]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    )
    return [
        ROOT / os.fsdecode(item)
        for item in raw.split(b"\0")
        if item and (ROOT / os.fsdecode(item)).is_file()
    ]

def main() -> None:
    if not OLD.is_dir():
        raise SystemExit("Expected the tracked 'aether/' package directory.")
    if NEW.exists():
        raise SystemExit("Refusing to overwrite an existing 'crows/' directory.")

    changed = 0
    for path in tracked_files():
        if path == Path(__file__):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        updated = data
        for before, after in REPLACEMENTS:
            updated = updated.replace(before, after)
        if updated != data:
            path.write_bytes(updated)
            changed += 1

    OLD.rename(NEW)
    print(f"Renamed aether/ -> crows/ and updated {changed} tracked text files.")
    print("Review carefully: compatibility identifiers were intentionally preserved.")
    print("Next: python -m pip install -e '.[dev]' && python -m pytest -q")

if __name__ == "__main__":
    main()
