#!/usr/bin/env python3
"""Batch-generate Unity scene JSON files from optimized layout JSONs.

This is the production-style generator for the current milestone:

raw optimized layouts -> rule/procedural or ML-guided Unity scene JSONs
-> validation summary report.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import generate_ml_guided_scene as ml_scene  # noqa: E402
from layout_to_scene import compile_layout, write_json  # noqa: E402


DEFAULT_CATALOG = (
    ROOT / "config" / "asset_catalog.generated.json"
    if (ROOT / "config" / "asset_catalog.generated.json").exists()
    else ROOT / "config" / "asset_catalog.json"
)


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


def issue_counts(scene: dict[str, Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for issue in scene.get("validation_report", {}).get("issues", []):
        counter[str(issue.get("type", "unknown"))] += 1
    return dict(counter)


def scene_record(
    layout_path: Path,
    output_path: Path,
    mode: str,
    seed: int,
    scene: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    validation = scene.get("validation_report", {})
    stats = scene.get("stats", {})
    record = {
        "layout": str(layout_path),
        "output": str(output_path),
        "mode": mode,
        "seed": seed,
        "scene_id": scene.get("scene_id"),
        "validation_status": validation.get("status"),
        "issue_count": validation.get("issue_count", 0),
        "issue_counts": issue_counts(scene),
        "object_count": stats.get("object_count", 0),
        "primary_count": stats.get("primary_count", 0),
        "accessory_count": stats.get("accessory_count", 0),
        "rule_scatter_count": stats.get("rule_scatter_count", 0),
        "elapsed_seconds": elapsed_seconds,
    }
    if mode == "ml_guided":
        guidance = scene.get("ml_guidance", {})
        asset_selection = guidance.get("asset_selection", {})
        placement = guidance.get("placement", {})
        record.update(
            {
                "ml_retained_added_count": asset_selection.get("retained_ml_added_count", 0),
                "ml_proposed_added_count": asset_selection.get("added_count", 0),
                "ml_incompatible_count": asset_selection.get("incompatible_count", 0),
                "ml_placement_accepted_count": placement.get("accepted_count", 0),
                "ml_placement_rejected_count": placement.get("rejected_count", 0),
            }
        )
    return record


def build_rule_scene(args: argparse.Namespace, layout_path: Path, seed: int) -> dict[str, Any]:
    return compile_layout(
        input_path=layout_path,
        defaults_path=args.defaults,
        catalog_path=args.catalog,
        scatter_seed=seed,
        enable_scatter=not args.no_scatter,
    )


def build_ml_scene(
    args: argparse.Namespace,
    layout_path: Path,
    output_path: Path,
    seed: int,
    asset_model_bundle: tuple[Any, dict[str, Any]],
    placement_model_bundle: tuple[Any, dict[str, Any]],
) -> dict[str, Any]:
    defaults = load_json(args.defaults)
    scene = compile_layout(
        input_path=layout_path,
        defaults_path=args.defaults,
        catalog_path=args.catalog,
        scatter_seed=seed,
        enable_scatter=not args.no_scatter,
    )
    write_json(output_path, scene)

    asset_model, asset_checkpoint = asset_model_bundle
    placement_model, placement_checkpoint = placement_model_bundle
    zone_predictions = ml_scene.predict_zone_assets(output_path, asset_model, asset_checkpoint, args.asset_top_k)
    ml_added, add_report = ml_scene.add_ml_selected_accessories(
        scene,
        output_path,
        defaults,
        zone_predictions,
        args.asset_probability_threshold,
        args.ml_extras_per_zone,
        seed,
        semantic_filter=not args.disable_semantic_filter,
    )
    scene["objects"].extend(ml_added)
    placement_report = ml_scene.apply_ml_placements(
        scene,
        output_path,
        placement_model,
        placement_checkpoint,
        args.min_spacing,
    )
    scene["pipeline"]["name"] = "pair2scene-lite-construction-ml-guided"
    scene["pipeline"]["version"] = "0.2.0"
    scene["pipeline"]["description"] = (
        "Raw layout JSON -> hybrid ML asset selection and relation-aware "
        "accessory placement -> validated Unity scene JSON"
    )
    scene["ml_guidance"] = {
        "enabled": True,
        "asset_model": str(args.asset_model),
        "placement_model": str(args.placement_model),
        "asset_probability_threshold": args.asset_probability_threshold,
        "asset_top_k": args.asset_top_k,
        "ml_extras_per_zone": args.ml_extras_per_zone,
        "semantic_filter_enabled": not args.disable_semantic_filter,
        "asset_selection": {
            "zone_predictions": {
                zone_id: [
                    {"prefab_name": item["prefab_name"], "probability": round(float(item["probability"]), 4)}
                    for item in predictions
                ]
                for zone_id, predictions in zone_predictions.items()
            },
            **add_report,
        },
        "placement": placement_report,
        "notes": [
            "Primary optimized layout facilities are unchanged.",
            "ML-selected accessories are filtered through facility-type semantic compatibility.",
            "ML-predicted placements are kept only if they pass validation constraints.",
        ],
    }
    ml_scene.rebuild_scene_graph(scene)
    scene["ml_guidance"]["asset_selection"]["retained_ml_added_count"] = sum(
        1 for obj in scene["objects"] if obj.get("source", {}).get("placement_source") == "ml_zone_asset_model"
    )
    return scene


def mode_output_name(layout_path: Path, mode: str, seed: int) -> str:
    return f"{layout_path.stem}_seed_{seed:03d}_{mode}_unity_scene.json"


def write_report(output_root: Path, records: list[dict[str, Any]], failures: list[dict[str, Any]], args: argparse.Namespace, elapsed: float) -> None:
    status_counts = Counter(record["validation_status"] for record in records)
    issue_type_counts: Counter[str] = Counter()
    for record in records:
        issue_type_counts.update(record.get("issue_counts", {}))

    report = {
        "input_dir": str(args.input_dir),
        "pattern": args.pattern,
        "safe_only": args.safe_only,
        "modes": args.mode,
        "seeds": args.seeds,
        "layout_limit": args.limit,
        "scene_count": len(records),
        "failure_count": len(failures),
        "validation_status_counts": dict(status_counts),
        "issue_type_counts": dict(issue_type_counts),
        "elapsed_seconds": elapsed,
        "outputs": {
            "scene_dir": str(output_root / "scenes"),
            "records_jsonl": str(output_root / "scene_records.jsonl"),
            "report_json": str(output_root / "batch_report.json"),
        },
        "failures": failures[:100],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    with (output_root / "batch_report.json").open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2)
    with (output_root / "scene_records.jsonl").open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--pattern", default="cslpelite_layout_*.json")
    parser.add_argument("--output-root", type=Path, default=ROOT / "output" / "batch_unity_scenes")
    parser.add_argument("--defaults", type=Path, default=ROOT / "config" / "facility_defaults.json")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--mode", choices=["rule", "ml_guided"], nargs="+", default=["ml_guided"])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--safe-only", action="store_true")
    parser.add_argument("--no-scatter", action="store_true")
    parser.add_argument(
        "--asset-model",
        type=Path,
        default=ROOT / "models" / "zone_asset_mlp" / "zone_asset_mlp.pt",
    )
    parser.add_argument(
        "--placement-model",
        type=Path,
        default=ROOT / "models" / "zone_asset_placement_mlp_accessory" / "zone_asset_placement_mlp.pt",
    )
    parser.add_argument("--asset-top-k", type=int, default=8)
    parser.add_argument("--asset-probability-threshold", type=float, default=0.6)
    parser.add_argument("--ml-extras-per-zone", type=int, default=1)
    parser.add_argument("--disable-semantic-filter", action="store_true")
    parser.add_argument("--min-spacing", type=float, default=0.15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = perf_counter()
    layouts = find_layouts(args.input_dir, args.pattern, args.safe_only)
    if args.limit is not None:
        layouts = layouts[: args.limit]
    if not layouts:
        raise SystemExit("No compatible layout JSON files found.")

    scene_dir = args.output_root / "scenes"
    scene_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    asset_model_bundle = None
    placement_model_bundle = None
    if "ml_guided" in args.mode:
        asset_model_bundle = ml_scene.load_asset_model(args.asset_model)
        placement_model_bundle = ml_scene.load_placement_model(args.placement_model)

    total_jobs = len(layouts) * len(args.seeds) * len(args.mode)
    completed = 0
    print(f"Layouts: {len(layouts)}")
    print(f"Modes: {args.mode}")
    print(f"Seeds: {args.seeds}")
    print(f"Jobs: {total_jobs}")

    for layout_index, layout_path in enumerate(layouts, start=1):
        for seed in args.seeds:
            for mode in args.mode:
                output_path = scene_dir / mode_output_name(layout_path, mode, seed)
                job_start = perf_counter()
                try:
                    if mode == "rule":
                        scene = build_rule_scene(args, layout_path, seed)
                    else:
                        assert asset_model_bundle is not None
                        assert placement_model_bundle is not None
                        scene = build_ml_scene(args, layout_path, output_path, seed, asset_model_bundle, placement_model_bundle)
                    write_json(output_path, scene)
                    records.append(scene_record(layout_path, output_path, mode, seed, scene, perf_counter() - job_start))
                except Exception as exc:
                    failures.append(
                        {
                            "layout": str(layout_path),
                            "mode": mode,
                            "seed": seed,
                            "error": repr(exc),
                        }
                    )
                completed += 1
        if layout_index % 25 == 0 or layout_index == len(layouts):
            print(f"Processed {layout_index}/{len(layouts)} layouts ({completed}/{total_jobs} jobs).")

    elapsed = perf_counter() - start
    write_report(args.output_root, records, failures, args, elapsed)
    status_counts = Counter(record["validation_status"] for record in records)
    print(f"Scenes written: {len(records)}")
    print(f"Failures: {len(failures)}")
    print(f"Validation: {dict(status_counts)}")
    print(f"Wrote report: {args.output_root / 'batch_report.json'}")
    print(f"Wrote records: {args.output_root / 'scene_records.jsonl'}")


if __name__ == "__main__":
    main()
