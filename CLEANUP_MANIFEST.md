# Cleanup Manifest

The project has been hard-cleaned into this `scene_pipeline/` folder.

## Active Contents

- `config/`
  - `asset_catalog.generated.json`
  - `asset_catalog.json`
  - `facility_defaults.json`
  - `construction_asset_inventory.csv`
- `models/`
  - `zone_asset_mlp/`
  - `zone_asset_placement_mlp/`
  - `zone_asset_placement_mlp_accessory/`
  - `scene_realism_mlp/`
- `scripts/`
  - rule-based compiler
  - ML-guided compiler
  - batch generator
  - ML dataset/training utilities
  - asset catalog and asset-kit diagnostics
- `unity/ConstructionSceneImporter.cs`
- `examples/`
  - Bulleen and standard sample layouts
- `data/`
  - current imported optimization-layout dataset for batch generation
- `output/`
  - latest single-layout Unity scene JSONs
  - `batch_safe_ml_guided/` production batch output

## Deleted During Cleanup

- root-level copied `ConstructionSite/` asset pack
- root-level trial `output/` folder
- old smoke-test folders
- old first-iteration ML experiment outputs
- old single-scene trial JSONs
- temporary verification outputs

The full Unity HDRP prefab assets still belong in the Unity project. This repository only needs prefab paths, catalogs, generated scene JSON, and the importer script.

## External CEXO Source

Known CEXO study folder:

`C:\Users\Ping\Documents\Visual studio code repo\2026\CSLP v5 (official)\bulleen_study`

It contains `core`, `media`, `results`, and `vendor`. Next week, the user-friendly interface can connect either to this CEXO result folder directly or to an exported JSON folder copied into `scene_pipeline/data/`.
