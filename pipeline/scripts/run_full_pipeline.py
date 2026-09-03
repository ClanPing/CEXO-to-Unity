#!/usr/bin/env python3
"""Run the integrated layout-generation and layout-to-scene pipeline.

The full workflow has two modes:

- use existing raw layout JSONs, or
- run a trusted local layout-generation command first, then compile the JSONs.

The output is a folder of Unity-ready scene JSONs plus reports that can be
opened with the Unity Scene Browser.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def run_command(command: list[str], cwd: Path) -> None:
    print("Running:", " ".join(str(part) for part in command))
    completed = subprocess.run(command, cwd=cwd)
    if completed.returncode != 0:
        raise SystemExit(f"Command failed with exit code {completed.returncode}: {' '.join(command)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--layout-command",
        help=(
            "Optional trusted local command that generates raw layout JSONs before Stage 2 runs. "
            "If omitted, --layout-output-dir is treated as an existing layout folder."
        ),
    )
    parser.add_argument("--layout-output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--layout-pattern", default="cslpelite_layout_*.json")
    parser.add_argument("--scene-output-root", type=Path, default=ROOT / "output" / "full_pipeline")
    parser.add_argument("--mode", choices=["rule", "ml_guided"], nargs="+", default=["ml_guided"])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--safe-only", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-scatter", action="store_true")
    parser.add_argument("--asset-top-k", type=int, default=8)
    parser.add_argument("--asset-probability-threshold", type=float, default=0.6)
    parser.add_argument("--ml-extras-per-zone", type=int, default=1)
    parser.add_argument("--min-spacing", type=float, default=0.15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = perf_counter()
    args.scene_output_root.mkdir(parents=True, exist_ok=True)

    stage1_manifest = args.scene_output_root / "layout_manifest.json"
    stage1_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_layout_generation.py"),
        "--output-dir",
        str(args.layout_output_dir),
        "--pattern",
        args.layout_pattern,
        "--manifest",
        str(stage1_manifest),
    ]
    if args.safe_only:
        stage1_cmd.append("--safe-only")
    if args.limit is not None:
        stage1_cmd.extend(["--limit", str(args.limit)])
    if args.layout_command:
        stage1_cmd.extend(["--command", args.layout_command])
    run_command(stage1_cmd, ROOT)

    stage2_cmd = [
        sys.executable,
        str(ROOT / "scripts" / "batch_generate_unity_scenes.py"),
        "--input-dir",
        str(args.layout_output_dir),
        "--pattern",
        args.layout_pattern,
        "--output-root",
        str(args.scene_output_root),
        "--mode",
        *args.mode,
        "--seeds",
        *[str(seed) for seed in args.seeds],
        "--asset-top-k",
        str(args.asset_top_k),
        "--asset-probability-threshold",
        str(args.asset_probability_threshold),
        "--ml-extras-per-zone",
        str(args.ml_extras_per_zone),
        "--min-spacing",
        str(args.min_spacing),
    ]
    if args.safe_only:
        stage2_cmd.append("--safe-only")
    if args.limit is not None:
        stage2_cmd.extend(["--limit", str(args.limit)])
    if args.no_scatter:
        stage2_cmd.append("--no-scatter")
    run_command(stage2_cmd, ROOT)

    batch_report_path = args.scene_output_root / "batch_report.json"
    batch_report = load_json(batch_report_path) if batch_report_path.exists() else {}
    report = {
        "stage": "full_pipeline",
        "layout_output_dir": str(args.layout_output_dir),
        "layout_pattern": args.layout_pattern,
        "scene_output_root": str(args.scene_output_root),
        "mode": args.mode,
        "seeds": args.seeds,
        "safe_only": args.safe_only,
        "limit": args.limit,
        "elapsed_seconds": perf_counter() - start,
        "outputs": {
            "layout_manifest": str(stage1_manifest),
            "scene_dir": str(args.scene_output_root / "scenes"),
            "batch_report": str(batch_report_path),
            "full_report": str(args.scene_output_root / "full_pipeline_report.json"),
        },
        "batch_summary": {
            "scene_count": batch_report.get("scene_count"),
            "failure_count": batch_report.get("failure_count"),
            "validation_status_counts": batch_report.get("validation_status_counts", {}),
        },
    }
    write_json(args.scene_output_root / "full_pipeline_report.json", report)

    print(f"Full pipeline complete.")
    print(f"Scene JSONs: {args.scene_output_root / 'scenes'}")
    print(f"Report: {args.scene_output_root / 'full_pipeline_report.json'}")


if __name__ == "__main__":
    main()
