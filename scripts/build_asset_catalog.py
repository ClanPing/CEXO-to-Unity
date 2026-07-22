#!/usr/bin/env python3
"""Build a semantic prefab catalog from the Unity construction asset inventory."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

FACILITY_CLASS_MAP = {
    "core": {"scaffold", "building_element"},
    "crane": {"crane"},
    "storage": {"material", "pallet", "container"},
    "office": {"container"},
    "rest_area": {"toilet", "container", "small_prop"},
}

PRIMARY_CLASS = {
    "core": "scaffold",
    "crane": "crane",
    "storage": "material",
    "office": "container",
    "rest_area": "toilet",
}

PREFERRED_NAME_TERMS = {
    "core": ("Scaffolding", "Formwork", "ConcreteWall"),
    "crane": ("TowerCrane",),
    "storage": ("ConcreteBrick", "ConcreteBag", "Pallet", "StoragePipe", "ReinforcementBar"),
    "office": ("CargoContainer", "Container"),
    "rest_area": ("Biotoilet", "WaterTank", "CargoContainer"),
}


def tower_crane_composite() -> dict[str, Any]:
    return {
        "name": "COMPOSITE_TowerCrane",
        "path": "",
        "folder_category": "towercrane",
        "construction_class": "crane",
        "relation_role": "major_anchor",
        "suggested_support_type": "heavy_grounded",
        "pivot_type": "bottom_centered",
        "snap_to_ground": True,
        "has_collider": True,
        "bbox_size": {"x": 8.0, "y": 36.0, "z": 52.0},
        "selection_score": 999.0,
        "assembly_type": "compound_prefab",
        "children": [
            {
                "name": "SM_TowerCrane01_base",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane01.prefab",
                "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane02_mast_01",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane02.prefab",
                "position": {"x": 0.0, "y": 4.5, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane02_mast_02",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane02.prefab",
                "position": {"x": 0.0, "y": 9.1, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane02_mast_03",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane02.prefab",
                "position": {"x": 0.0, "y": 13.7, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane02_mast_04",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane02.prefab",
                "position": {"x": 0.0, "y": 18.3, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane02_mast_05",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane02.prefab",
                "position": {"x": 0.0, "y": 22.9, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane06_upper_jib",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane06.prefab",
                "position": {"x": 0.0, "y": 28.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_TowerCrane13_hook_line",
                "path": "Assets/ConstructionSite/Prefab/TowerCrane/SM_TowerCrane13.prefab",
                "position": {"x": 0.0, "y": 23.5, "z": 17.5},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            }
        ],
        "notes": "Approximate tower-crane assembly from component prefabs. Local offsets are intended for visual testing and should be tuned in Unity."
    }


def construction_core_composite() -> dict[str, Any]:
    return {
        "name": "COMPOSITE_ConstructionCore",
        "path": "",
        "folder_category": "building",
        "construction_class": "building_element",
        "relation_role": "support_or_anchor",
        "suggested_support_type": "structural_support",
        "pivot_type": "bottom_centered",
        "snap_to_ground": True,
        "has_collider": True,
        "bbox_size": {"x": 8.0, "y": 8.0, "z": 10.0},
        "selection_score": 998.0,
        "assembly_type": "compound_prefab",
        "children": [
            {
                "name": "SM_ConcreteFloor01_floor_a",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_ConcreteFloor01.prefab",
                "position": {"x": -2.0, "y": 0.0, "z": -2.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_ConcreteFloor01_floor_b",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_ConcreteFloor01.prefab",
                "position": {"x": 2.0, "y": 0.0, "z": -2.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_ConcreteFloor01_floor_c",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_ConcreteFloor01.prefab",
                "position": {"x": -2.0, "y": 0.0, "z": 2.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_ConcreteFloor01_floor_d",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_ConcreteFloor01.prefab",
                "position": {"x": 2.0, "y": 0.0, "z": 2.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Formwork03_core_frame",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_Formwork03.prefab",
                "position": {"x": 0.0, "y": 0.2, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Formwork02_side_frame",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_Formwork02.prefab",
                "position": {"x": 3.4, "y": 0.2, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Scaffolding23_front_bay",
                "path": "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding23.prefab",
                "position": {"x": 0.0, "y": 0.0, "z": -4.5},
                "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Scaffolding23_back_bay",
                "path": "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding23.prefab",
                "position": {"x": 0.0, "y": 0.0, "z": 4.5},
                "rotation": {"x": 0.0, "y": 90.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Scaffolding20_left_bay",
                "path": "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding20.prefab",
                "position": {"x": -4.5, "y": 0.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Scaffolding20_right_bay",
                "path": "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding20.prefab",
                "position": {"x": 4.5, "y": 0.0, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            },
            {
                "name": "SM_Tarp09_top_cover",
                "path": "Assets/ConstructionSite/Prefab/Building/SM_Tarp09.prefab",
                "position": {"x": 0.0, "y": 6.3, "z": 0.0},
                "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
                "scale": {"x": 1.0, "y": 1.0, "z": 1.0}
            }
        ],
        "notes": "Approximate building-core assembly using formwork, concrete floor, scaffolding bays, and tarp cover."
    }


def prefab_child(
    name: str,
    path: str,
    x: float,
    y: float,
    z: float,
    ry: float = 0.0,
    sx: float = 1.0,
    sy: float = 1.0,
    sz: float = 1.0,
) -> dict[str, Any]:
    return {
        "name": name,
        "path": path,
        "position": {"x": x, "y": y, "z": z},
        "rotation": {"x": 0.0, "y": ry, "z": 0.0},
        "scale": {"x": sx, "y": sy, "z": sz},
    }


def construction_core_wall_composite() -> dict[str, Any]:
    floor_path = "Assets/ConstructionSite/Prefab/Building/SM_ConcreteFloor01.prefab"
    wall_path = "Assets/ConstructionSite/Prefab/Building/SM_ConcreteWall02.prefab"
    column_path = "Assets/ConstructionSite/Prefab/Building/SM_ConcreteColumn01.prefab"
    formwork_path = "Assets/ConstructionSite/Prefab/Building/SM_Formwork04.prefab"
    scaffold_path = "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding21.prefab"
    return {
        "name": "COMPOSITE_ConstructionCore_Walls",
        "path": "",
        "folder_category": "building",
        "construction_class": "building_element",
        "relation_role": "support_or_anchor",
        "suggested_support_type": "structural_support",
        "pivot_type": "bottom_centered",
        "snap_to_ground": True,
        "has_collider": True,
        "bbox_size": {"x": 8.0, "y": 8.0, "z": 10.0},
        "selection_score": 997.0,
        "assembly_type": "compound_prefab",
        "children": [
            prefab_child("SM_ConcreteFloor01_floor_a", floor_path, -2.0, 0.0, -2.0),
            prefab_child("SM_ConcreteFloor01_floor_b", floor_path, 2.0, 0.0, -2.0),
            prefab_child("SM_ConcreteFloor01_floor_c", floor_path, -2.0, 0.0, 2.0),
            prefab_child("SM_ConcreteFloor01_floor_d", floor_path, 2.0, 0.0, 2.0),
            prefab_child("SM_ConcreteWall02_wall_front", wall_path, 0.0, 0.0, -4.0, 90.0),
            prefab_child("SM_ConcreteWall02_wall_back", wall_path, 0.0, 0.0, 4.0, 90.0),
            prefab_child("SM_ConcreteWall02_wall_left", wall_path, -4.0, 0.0, 0.0, 0.0),
            prefab_child("SM_ConcreteWall02_wall_right_open", wall_path, 4.0, 0.0, -1.8, 0.0),
            prefab_child("SM_ConcreteColumn01_column_a", column_path, -3.4, 0.0, -3.4),
            prefab_child("SM_ConcreteColumn01_column_b", column_path, 3.4, 0.0, -3.4),
            prefab_child("SM_ConcreteColumn01_column_c", column_path, -3.4, 0.0, 3.4),
            prefab_child("SM_Formwork04_inner_formwork", formwork_path, 0.0, 0.2, 0.0),
            prefab_child("SM_Scaffolding21_access_bay", scaffold_path, 4.7, 0.0, 2.8),
        ],
        "notes": "Alternative core variant using concrete wall segments, columns, inner formwork, and one scaffold access bay."
    }


def construction_core_lift_composite() -> dict[str, Any]:
    floor_path = "Assets/ConstructionSite/Prefab/Building/SM_ConcreteFloor01.prefab"
    scaffold_path = "Assets/ConstructionSite/Prefab/Building/Scaffolding/SM_Scaffolding23.prefab"
    lift_path = "Assets/ConstructionSite/Prefab/ConstructionSite/SM_ConstructionLift05.prefab"
    tarp_path = "Assets/ConstructionSite/Prefab/Building/SM_Tarp12.prefab"
    reinforcement_path = "Assets/ConstructionSite/Prefab/Building/SM_FormworkReinforcment03.prefab"
    return {
        "name": "COMPOSITE_ConstructionCore_Lift",
        "path": "",
        "folder_category": "building",
        "construction_class": "building_element",
        "relation_role": "support_or_anchor",
        "suggested_support_type": "structural_support",
        "pivot_type": "bottom_centered",
        "snap_to_ground": True,
        "has_collider": True,
        "bbox_size": {"x": 8.0, "y": 8.0, "z": 10.0},
        "selection_score": 996.0,
        "assembly_type": "compound_prefab",
        "children": [
            prefab_child("SM_ConcreteFloor01_floor_a", floor_path, -2.0, 0.0, -2.0),
            prefab_child("SM_ConcreteFloor01_floor_b", floor_path, 2.0, 0.0, -2.0),
            prefab_child("SM_ConcreteFloor01_floor_c", floor_path, -2.0, 0.0, 2.0),
            prefab_child("SM_ConcreteFloor01_floor_d", floor_path, 2.0, 0.0, 2.0),
            prefab_child("SM_FormworkReinforcment03_rebar_a", reinforcement_path, -1.7, 0.0, -1.7),
            prefab_child("SM_FormworkReinforcment03_rebar_b", reinforcement_path, 1.7, 0.0, 1.7, 180.0),
            prefab_child("SM_Scaffolding23_front_bay", scaffold_path, 0.0, 0.0, -4.5, 90.0),
            prefab_child("SM_Scaffolding23_side_bay", scaffold_path, -4.4, 0.0, 0.0, 0.0),
            prefab_child("SM_ConstructionLift05_service_lift", lift_path, 4.8, 0.0, 0.0, 90.0),
            prefab_child("SM_Tarp12_partial_cover", tarp_path, -1.0, 5.8, 1.0, 15.0),
        ],
        "notes": "Alternative core variant with scaffold bays, reinforcement cages, partial cover, and a service lift."
    }


def construction_core_composites() -> list[dict[str, Any]]:
    return [
        construction_core_composite(),
        construction_core_wall_composite(),
        construction_core_lift_composite(),
    ]


def to_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_bool(value: str) -> bool:
    return str(value).strip().lower() == "true"


def candidate_score(row: dict[str, str], facility_type: str) -> float:
    score = 0.0
    size_x = to_float(row.get("SizeX", "0"))
    size_y = to_float(row.get("SizeY", "0"))
    size_z = to_float(row.get("SizeZ", "0"))

    if row["AssetType"] == "Prefab":
        score += 4.0
    if row["ConstructionClass"] in FACILITY_CLASS_MAP[facility_type]:
        score += 3.0
    if row["ConstructionClass"] == PRIMARY_CLASS[facility_type]:
        score += 3.0
    if any(term.lower() in row["Name"].lower() for term in PREFERRED_NAME_TERMS[facility_type]):
        score += 2.0
    if to_bool(row["HasCollider"]):
        score += 0.5
    if row["PivotType"] == "bottom_centered":
        score += 0.5
    if not to_bool(row["NeedsScaleCheck"]):
        score += 0.25
    if facility_type == "crane":
        # Prefer complete crane assemblies over isolated base/boom fragments.
        score += min(size_y / 4.0, 5.0)
        score += min(max(size_x, size_z) / 10.0, 4.0)
    elif facility_type == "storage":
        # Avoid nearly invisible thin single bars when a broader material stack exists.
        score += min((size_x * size_z) / 4.0, 2.0)
    return score


def prefab_candidate(row: dict[str, str], facility_type: str) -> dict[str, Any]:
    return {
        "name": row["Name"],
        "path": row["AssetPath"],
        "folder_category": row["FolderCategory"],
        "construction_class": row["ConstructionClass"],
        "relation_role": row["RelationRole"],
        "suggested_support_type": row["SuggestedSupportType"],
        "pivot_type": row["PivotType"],
        "snap_to_ground": to_bool(row["SnapToGround"]),
        "has_collider": to_bool(row["HasCollider"]),
        "bbox_size": {
            "x": to_float(row["SizeX"]),
            "y": to_float(row["SizeY"]),
            "z": to_float(row["SizeZ"]),
        },
        "selection_score": round(candidate_score(row, facility_type), 3),
    }


def build_catalog(inventory_path: Path, top_k: int) -> dict[str, list[dict[str, Any]]]:
    with inventory_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    prefabs = [row for row in rows if row.get("AssetType") == "Prefab"]
    catalog: dict[str, list[dict[str, Any]]] = {}

    for facility_type, classes in FACILITY_CLASS_MAP.items():
        matching = [
            row
            for row in prefabs
            if row.get("ConstructionClass") in classes
            or any(term.lower() in row.get("Name", "").lower() for term in PREFERRED_NAME_TERMS[facility_type])
        ]
        matching.sort(key=lambda row: candidate_score(row, facility_type), reverse=True)
        catalog[facility_type] = [prefab_candidate(row, facility_type) for row in matching[:top_k]]

    catalog["core"] = construction_core_composites() + catalog["core"]
    catalog["crane"].insert(0, tower_crane_composite())
    catalog["unknown"] = [
        prefab_candidate(row, "storage")
        for row in prefabs
        if row.get("ConstructionClass") in {"material", "small_prop", "unclassified"}
    ][:top_k]
    return catalog


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
        default=ROOT / "config" / "asset_catalog.generated.json",
    )
    parser.add_argument("--top-k", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = build_catalog(args.inventory.resolve(), args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(catalog, file, indent=2)
        file.write("\n")
    print(f"Wrote {args.output}")
    for key, values in catalog.items():
        print(f"{key}: {len(values)} candidates")


if __name__ == "__main__":
    main()
