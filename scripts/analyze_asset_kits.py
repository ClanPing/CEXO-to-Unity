#!/usr/bin/env python3
"""Infer kit-style prefab roles from the construction asset inventory."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def numeric_family(name: str) -> str:
    return re.sub(r"\d+(?:_\d+)?$", "", name)


def classify_geometry(row: dict[str, str]) -> str:
    x = to_float(row["SizeX"])
    y = to_float(row["SizeY"])
    z = to_float(row["SizeZ"])
    dims = sorted([x, y, z])
    smallest, middle, largest = dims

    if largest <= 0:
        return "unknown"
    if smallest / largest < 0.08 and middle / largest < 0.18:
        return "linear_member"
    if smallest / largest < 0.08 and middle / largest >= 0.18:
        return "panel_or_sheet"
    if y > 2.0 and x < 0.5 and z < 0.5:
        return "vertical_post"
    if y < 0.5 and max(x, z) > 1.0:
        return "deck_or_horizontal_member"
    if x > 1.0 and y > 1.0 and z > 1.0:
        return "volumetric_module"
    return "small_part"


def semantic_role(row: dict[str, str]) -> str:
    name = row["Name"].lower()
    construction_class = row["ConstructionClass"]
    geometry = classify_geometry(row)

    if "towercrane" in name:
        if geometry in {"vertical_post", "volumetric_module"} and to_float(row["SizeY"]) > 8:
            return "crane_mast_or_body"
        if to_float(row["SizeZ"]) > 10 or to_float(row["SizeX"]) > 10:
            return "crane_jib_or_boom"
        if to_float(row["SizeY"]) < 3:
            return "crane_hook_or_small_part"
        return "crane_base_or_segment"

    if "scaffolding" in name or construction_class == "scaffold":
        if geometry == "vertical_post":
            return "scaffold_post"
        if geometry == "panel_or_sheet":
            return "scaffold_panel"
        if geometry == "deck_or_horizontal_member":
            return "scaffold_deck_or_rail"
        if geometry == "volumetric_module":
            return "scaffold_bay"
        return "scaffold_small_part"

    if construction_class == "material":
        if geometry == "linear_member":
            return "linear_material"
        if geometry == "volumetric_module":
            return "material_stack"
        return "material_part"

    return construction_class or "unclassified"


def build_understanding(inventory_path: Path) -> dict[str, Any]:
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = [row for row in csv.DictReader(file) if row.get("AssetType") == "Prefab"]

    assets = []
    for row in rows:
        role = semantic_role(row)
        assets.append(
            {
                "name": row["Name"],
                "path": row["AssetPath"],
                "folder_category": row["FolderCategory"],
                "construction_class": row["ConstructionClass"],
                "family": numeric_family(row["Name"]),
                "geometry_role": classify_geometry(row),
                "semantic_role": role,
                "size": {
                    "x": to_float(row["SizeX"]),
                    "y": to_float(row["SizeY"]),
                    "z": to_float(row["SizeZ"]),
                },
                "child_count": int(float(row["ChildCount"] or 0)),
                "renderer_count": int(float(row["RendererCount"] or 0)),
                "has_collider": row["HasCollider"].lower() == "true",
            }
        )

    roles: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        roles.setdefault(asset["semantic_role"], []).append(asset)

    for role_assets in roles.values():
        role_assets.sort(key=lambda item: (item["size"]["y"], item["size"]["x"] * item["size"]["z"]), reverse=True)

    return {
        "asset_count": len(assets),
        "roles": roles,
        "recommended_assemblies": {
            "tower_crane": {
                "strategy": "compound assembly",
                "roles": ["crane_base_or_segment", "crane_mast_or_body", "crane_jib_or_boom", "crane_hook_or_small_part"],
                "notes": "Requires hand-tuned local offsets or Unity-authored parent prefab.",
            },
            "scaffold_core": {
                "strategy": "modular tiling",
                "roles": ["scaffold_bay", "scaffold_panel", "scaffold_post", "scaffold_deck_or_rail"],
                "notes": "Use bays/panels repeatedly around the facility footprint; avoid single tiny parts as primary core assets.",
            },
            "storage_area": {
                "strategy": "material cluster",
                "roles": ["material_stack", "linear_material", "pallet"],
                "notes": "Fill the footprint with repeated material stacks rather than one object.",
            },
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=ROOT / "config" / "construction_asset_inventory.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "output" / "asset_kit_understanding.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_understanding(args.inventory.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
        file.write("\n")
    print(f"Wrote {args.output}")
    print(f"Assets: {result['asset_count']}")
    for role, assets in sorted(result["roles"].items()):
        print(f"{role}: {len(assets)}")


if __name__ == "__main__":
    main()
