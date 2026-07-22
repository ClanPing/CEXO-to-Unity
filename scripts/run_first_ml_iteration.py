"""Run the first end-to-end ML data iteration.

Pipeline:
raw optimized layout JSONs -> Unity scene JSON variants -> ML JSONL records
-> simple baselines -> iteration report.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from export_ml_dataset import export_scene, write_jsonl  # noqa: E402
from layout_to_scene import compile_layout, write_json  # noqa: E402
from train_ml_baselines import (  # noqa: E402
    evaluate_asset,
    evaluate_relation,
    split_by_scene,
    train_asset_baseline,
    train_relation_baseline,
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def is_layout_json(path: Path) -> bool:
    try:
        data = load_json(path)
    except Exception:
        return False
    required = {"id", "site_width_m", "site_length_m", "boundary_polygon", "facilities"}
    return required.issubset(data.keys())


def find_layouts(input_dir: Path, pattern: str, safe_only: bool) -> list[Path]:
    layouts = []
    for path in sorted(input_dir.glob(pattern)):
        if not path.is_file() or not is_layout_json(path):
            continue
        if safe_only:
            data = load_json(path)
            if not data.get("feasibility", {}).get("safe", False):
                continue
        layouts.append(path)
    return layouts


def compile_batch(
    layouts: list[Path],
    output_dir: Path,
    defaults: Path,
    catalog: Path,
    seeds: list[int],
    enable_scatter: bool,
) -> tuple[list[Path], list[dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_paths: list[Path] = []
    failures: list[dict[str, Any]] = []

    for layout_index, layout_path in enumerate(layouts, start=1):
        for seed in seeds:
            suffix = f"seed_{seed:03d}"
            output_path = output_dir / f"{layout_path.stem}_{suffix}_unity_scene.json"
            try:
                scene = compile_layout(
                    input_path=layout_path,
                    defaults_path=defaults,
                    catalog_path=catalog,
                    scatter_seed=seed,
                    enable_scatter=enable_scatter,
                )
                write_json(output_path, scene)
                scene_paths.append(output_path)
            except Exception as exc:
                failures.append(
                    {
                        "layout": str(layout_path),
                        "seed": seed,
                        "error": repr(exc),
                    }
                )
        if layout_index % 100 == 0:
            print(f"Compiled {layout_index}/{len(layouts)} layouts...")

    return scene_paths, failures


def export_dataset(scene_paths: list[Path], dataset_dir: Path) -> dict[str, Any]:
    dataset_dir.mkdir(parents=True, exist_ok=True)
    asset_rows: list[dict[str, Any]] = []
    relation_rows: list[dict[str, Any]] = []
    scene_rows: list[dict[str, Any]] = []

    for path in scene_paths:
        scene_asset_rows, scene_relation_rows, summary_row = export_scene(path)
        asset_rows.extend(scene_asset_rows)
        relation_rows.extend(scene_relation_rows)
        scene_rows.append(summary_row)

    write_jsonl(dataset_dir / "asset_selection.jsonl", asset_rows)
    write_jsonl(dataset_dir / "relation_placement.jsonl", relation_rows)
    write_jsonl(dataset_dir / "scene_realism.jsonl", scene_rows)

    manifest = {
        "scene_count": len(scene_paths),
        "asset_selection_records": len(asset_rows),
        "relation_placement_records": len(relation_rows),
        "scene_realism_records": len(scene_rows),
        "source_scenes": [str(path) for path in scene_paths],
        "files": {
            "asset_selection": str(dataset_dir / "asset_selection.jsonl"),
            "relation_placement": str(dataset_dir / "relation_placement.jsonl"),
            "scene_realism": str(dataset_dir / "scene_realism.jsonl"),
        },
    }
    with (dataset_dir / "manifest.json").open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
    return manifest


def train_baselines(dataset_dir: Path, baseline_dir: Path, test_fraction: float) -> dict[str, Any]:
    baseline_dir.mkdir(parents=True, exist_ok=True)
    asset_rows = [json.loads(line) for line in (dataset_dir / "asset_selection.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    relation_rows = [json.loads(line) for line in (dataset_dir / "relation_placement.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    asset_train, asset_test = split_by_scene(asset_rows, test_fraction)
    relation_train, relation_test = split_by_scene(relation_rows, test_fraction)

    asset_model = train_asset_baseline(asset_train)
    relation_model = train_relation_baseline(relation_train)
    metrics = {
        "asset_selection": {
            "train": evaluate_asset(asset_model, asset_train),
            "test": evaluate_asset(asset_model, asset_test),
        },
        "relation_placement": {
            "train": evaluate_relation(relation_model, relation_train),
            "test": evaluate_relation(relation_model, relation_test),
        },
        "split": {
            "asset_train_records": len(asset_train),
            "asset_test_records": len(asset_test),
            "relation_train_records": len(relation_train),
            "relation_test_records": len(relation_test),
            "test_fraction": test_fraction,
        },
    }

    with (baseline_dir / "asset_selection_baseline.json").open("w", encoding="utf-8") as file:
        json.dump(asset_model, file, indent=2)
    with (baseline_dir / "relation_placement_baseline.json").open("w", encoding="utf-8") as file:
        json.dump(relation_model, file, indent=2)
    with (baseline_dir / "metrics.json").open("w", encoding="utf-8") as file:
        json.dump(metrics, file, indent=2)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--pattern", default="cslpelite_layout_*.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "output" / "first_ml_iteration")
    parser.add_argument("--defaults", type=Path, default=ROOT / "config" / "facility_defaults.json")
    parser.add_argument("--catalog", type=Path, default=ROOT / "config" / "asset_catalog.generated.json")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum number of raw layouts to compile.")
    parser.add_argument("--safe-only", action="store_true", help="Use only optimization layouts marked feasibility.safe=true.")
    parser.add_argument("--no-scatter", action="store_true", help="Disable rule-based scatter during scene compilation.")
    parser.add_argument("--test-fraction", type=float, default=0.25)
    parser.add_argument("--clean", action="store_true", help="Delete the output root before running.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = perf_counter()
    if args.clean and args.output_root.exists():
        shutil.rmtree(args.output_root)

    layouts = find_layouts(args.input_dir, args.pattern, args.safe_only)
    if args.limit is not None:
        layouts = layouts[: args.limit]
    if not layouts:
        raise SystemExit("No compatible layout JSON files found.")

    scene_dir = args.output_root / "scenes"
    dataset_dir = args.output_root / "ml_dataset"
    baseline_dir = args.output_root / "ml_baselines"

    print(f"Layouts: {len(layouts)}")
    print(f"Seeds: {args.seeds}")
    scene_paths, failures = compile_batch(
        layouts=layouts,
        output_dir=scene_dir,
        defaults=args.defaults,
        catalog=args.catalog,
        seeds=args.seeds,
        enable_scatter=not args.no_scatter,
    )
    manifest = export_dataset(scene_paths, dataset_dir)
    metrics = train_baselines(dataset_dir, baseline_dir, args.test_fraction)

    elapsed_seconds = perf_counter() - start
    report = {
        "input_dir": str(args.input_dir),
        "pattern": args.pattern,
        "safe_only": args.safe_only,
        "scatter_enabled": not args.no_scatter,
        "layout_count": len(layouts),
        "seeds": args.seeds,
        "compiled_scene_count": len(scene_paths),
        "failure_count": len(failures),
        "failures": failures[:50],
        "dataset_manifest": manifest,
        "baseline_metrics": metrics,
        "elapsed_seconds": elapsed_seconds,
        "outputs": {
            "scene_dir": str(scene_dir),
            "dataset_dir": str(dataset_dir),
            "baseline_dir": str(baseline_dir),
        },
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    with (args.output_root / "iteration_report.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)

    print(f"Compiled scenes: {len(scene_paths)}")
    print(f"Failures: {len(failures)}")
    print(f"Asset records: {manifest['asset_selection_records']}")
    print(f"Relation records: {manifest['relation_placement_records']}")
    print(f"Asset test accuracy: {metrics['asset_selection']['test']['accuracy']}")
    print(f"Relation test MAE: {metrics['relation_placement']['test']}")
    print(f"Wrote report: {args.output_root / 'iteration_report.json'}")


if __name__ == "__main__":
    main()
