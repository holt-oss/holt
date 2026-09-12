"""Fail a release build that contains workspace or reproducibility data."""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from pathlib import Path


MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
FORBIDDEN_PARTS = {
    ".claude",
    ".holt",
    "data",
    "eval",
    "fixtures",
    "runs",
    "tests",
    "trajectories",
}


def _members(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    with tarfile.open(path, "r:gz") as archive:
        return archive.getnames()


def check_archive(path: Path) -> list[str]:
    errors: list[str] = []
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        errors.append(
            f"{path.name} is {path.stat().st_size:,} bytes; expected at most "
            f"{MAX_ARCHIVE_BYTES:,}"
        )

    members = _members(path)
    for member in members:
        parts = set(Path(member).parts)
        forbidden = sorted(parts & FORBIDDEN_PARTS)
        if forbidden:
            errors.append(f"{path.name} contains forbidden path {member!r}")
        if Path(member).name == "**What":
            errors.append(f"{path.name} contains unexpected workspace file {member!r}")

    names = {Path(member).name for member in members}
    for required in ("LICENSE", "NOTICE"):
        if required not in names:
            errors.append(f"{path.name} does not contain {required}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", type=Path, help="directory produced by `uv build`")
    args = parser.parse_args()

    archives = sorted(args.dist.glob("holt_cli-*.tar.gz")) + sorted(
        args.dist.glob("holt_cli-*.whl")
    )
    if len(archives) != 2:
        print(f"expected one sdist and one wheel in {args.dist}, found {len(archives)}")
        return 1

    errors = [error for path in archives for error in check_archive(path)]
    if errors:
        print("\n".join(errors))
        return 1

    for path in archives:
        print(f"ok {path.name} ({path.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
