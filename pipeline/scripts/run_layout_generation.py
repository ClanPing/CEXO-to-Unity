#!/usr/bin/env python3
"""Run or register the 2D layout-generation stage.

This repository mainly implements the layout-to-Unity scene compiler. The
quality-diversity optimiser can live in a separate project, so this script acts
as a small bridge:

1. optionally run a trusted local layout-generation command, then
2. scan the produced folder for compatible raw layout JSON files, and
3. write a manifest that Stage 2 can consume.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def is_layout_json(path: Path) -> bool:
    try:
        data = load_json(path)
    except Exception:
        return False
    required = {"id", "site_width_m", "site_length_m", "facilities"}
    return required.issubset(data.keys())


def find_layouts(input_dir: Path, pattern: str, safe_only: bool) -> list[Path]:
    layouts: list[Path] = []
    for path in sorted(input_dir.glob(pattern)):
        if not path.is_file() or not is_layout_json(path):
            continue
        if safe_only:
            data = load_json(path)
            if not data.get("feasibility", {}).get("safe", False):
                continue
        layouts.append(path)
    return layouts


def layout_record(path: Path, root: Path) -> dict[str, Any]:
    data = load_json(path)
    return {
        "path": str(path),
        "relative_path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "id": data.get("id"),
        "facility_count": len(data.get("facilities", [])),
        "safe": data.get("feasibility", {}).get("safe"),
        "objectives": data.get("objectives", {}),
        "behaviors": data.get("behaviors", {}),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--command",
        help=(
            "Optional trusted local command that generates raw layout JSONs. "
            "Example: \"python path/to/optimizer.py --output output/layout_generation/layouts\""
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--pattern", default="cslpelite_layout_*.json")
    parser.add_argument("--safe-only", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "output" / "layout_generation" / "layout_manifest.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = perf_counter()
    command_result: dict[str, Any] | None = None

    if args.command:
        print(f"Running layout-generation command: {args.command}")
        completed = subprocess.run(args.command, shell=True)
        command_result = {
            "command": args.command,
            "returncode": completed.returncode,
        }
        if completed.returncode != 0:
            raise SystemExit(f"Layout-generation command failed with exit code {completed.returncode}.")

    layouts = find_layouts(args.output_dir, args.pattern, args.safe_only)
    if args.limit is not None:
        layouts = layouts[: args.limit]
    if not layouts:
        raise SystemExit(f"No compatible layout JSON files found in {args.output_dir}.")

    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "stage": "layout_generation",
        "output_dir": str(args.output_dir),
        "pattern": args.pattern,
        "safe_only": args.safe_only,
        "limit": args.limit,
        "layout_count": len(layouts),
        "command_result": command_result,
        "elapsed_seconds": perf_counter() - start,
        "layouts": [layout_record(path, args.output_dir) for path in layouts],
    }
    with args.manifest.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)

    print(f"Layouts found: {len(layouts)}")
    print(f"Wrote manifest: {args.manifest}")
    print(f"Use as Stage 2 input: --input-dir {args.output_dir}")


if __name__ == "__main__":
    main()
