# Pair2Scene-Lite Construction Layout Compiler

This project converts raw construction-site layout JSON into a 3D-ready scene graph.

The current raw inputs are:

- `examples/bulleen_layout.json`
- `examples/standard_layout_021.json`

The compiler output is an enriched JSON file containing:

- site bounds, boundary polygon, entrances, and exclusion zones
- site-context visuals for roads, boundary, and entrances
- semantic prefab selection
- object transforms in 3D coordinates
- footprint and bounding-box metadata
- support and functional relations
- Pair2Scene-inspired generation order
- rule-based scene enrichment with constrained scatter placement
- validation report

## Run

From the repository root:

```powershell
cd .\scene_pipeline
```

```powershell
python .\scripts\build_asset_catalog.py
python .\scripts\layout_to_scene.py .\examples\bulleen_layout.json --catalog .\config\asset_catalog.generated.json -o .\output\bulleen_layout_unity_scene.json
python .\scripts\layout_to_scene.py .\examples\standard_layout_021.json --catalog .\config\asset_catalog.generated.json -o .\output\standard_layout_021_unity_scene.json
```

Outputs are written to `output/`.

The compiler also writes a `scene_enrichment` report into each output JSON. This records the deterministic seed, accepted scatter count, attempted candidate count, rejected candidate count, and the active placement rules.

To generate visual variants while keeping the primary facilities fixed:

```powershell
python .\scripts\layout_to_scene.py .\examples\bulleen_layout.json --catalog .\config\asset_catalog.generated.json --scatter-seed 1 -o .\output\bulleen_layout_seed_001_unity_scene.json
python .\scripts\layout_to_scene.py .\examples\bulleen_layout.json --catalog .\config\asset_catalog.generated.json --scatter-seed 2 -o .\output\bulleen_layout_seed_002_unity_scene.json
python .\scripts\layout_to_scene.py .\examples\bulleen_layout.json --catalog .\config\asset_catalog.generated.json --no-scatter -o .\output\bulleen_layout_no_scatter_unity_scene.json
```

The raw layout positions remain stable; the seed changes visual core variants, material combinations, clutter counts, local offsets, and rotations for scene dressing.

The enrichment pass now uses a broader set of uncategorised/site-detail prefabs:

- ground detail: dirt decals and trash decals
- small tools: ladders, toolbox, paint cans, hoses, workbench
- site equipment: concrete mixer, mobile generator, construction lift, floodlight stands
- storage variety: stock stacks, log tarp, plywood, plank, pipe, pallet, concrete bag/brick stacks
- road/context detail: traffic cones, barrels, road closures

Core objects also cycle through compound visual variants when a layout contains multiple cores:

- `COMPOSITE_ConstructionCore`: scaffold/formwork/tarp core
- `COMPOSITE_ConstructionCore_Walls`: concrete wall and column core
- `COMPOSITE_ConstructionCore_Lift`: scaffold/reinforcement core with service lift

## Unity Test Steps

Copy these files into the Unity project:

- `unity/ConstructionSceneImporter.cs` -> `Assets/Scripts/ConstructionSceneImporter.cs`
- `unity/Editor/ConstructionSceneBrowserWindow.cs` -> `Assets/Editor/ConstructionSceneBrowserWindow.cs`

In Unity, open:

```text
Tools -> CEXO to Unity -> Scene Browser
```

Then:

1. Click `Browse`.
2. Select a folder of generated scene JSONs, for example `output/batch_safe_ml_guided/scenes`.
3. Click a JSON scene from the list to replace the current generated scene.

The browser reads JSON files directly from the selected folder. You do not need to copy generated scenes into `Assets/StreamingAssets` for editor preview.

Scene Browser conveniences:

- `Previous Scene` / `Next Scene`: step through and immediately import scenes in the filtered list.
- `Reimport Selected Scene`: reloads the current selected scene.
- `Reveal JSON`: opens the selected JSON in the system file browser.
- `Filter`: narrows the scene list by filename.

Recommended settings for visual testing:

- `External Scene Json Path`: usually set automatically by the Scene Browser
- `Scene Json Asset`: optional fallback for JSON files imported into Unity
- `Streaming Assets Json`: optional runtime-style fallback
- `Clear Existing Generated Objects`: on
- `Scale To Layout Footprint`: off
- `Create Site Ground`: on
- `Create Road Surfaces`: on
- `Create Boundary Fence`: on
- `Create Entrance Markers`: on
- `Use Prefab Site Context`: on
- `Create Boundary Road Block Clusters`: on
- `Create Entrance Road Blocks`: off
- `Create Uneven Site Ground`: optional; on if you want subtle rough ground
- `Create Footprint Markers`: off
- `Snap Renderer Bounds To Ground`: on

`Use Prefab Site Context` uses real catalogue prefabs for boundary fence modules, entrance gates, and road blocks. If a prefab path is missing, the importer falls back to simple primitive markers.

Useful tuning values:

- `Fence Module Spacing`: lower this slightly if visible gaps remain between fence modules.
- `Entrance Opening Width`: controls both the fence cutout around gates and the spread of gate panels.
- `Create Entrance Gate Panels`: off by default because the current `SM_Gate01` prefab does not match the perimeter fence opening reliably.
- `Entrance Gate Panel Count`: controls how many gate panels are placed across each entrance.
- `Entrance Gate Panel Spacing`: fallback spacing for single-panel entrance mode.
- `Create Entrance Road Blocks`: off by default so the entrance remains passable.
- `Entrance Road Block Side Offset`: controls how far road blocks sit to either side of the entrance opening.
- `Entrance Road Block Depth Offset`: controls how far road blocks sit in front of and behind the entrance line.
- `Boundary Road Block Spacing`: controls how often road blocks appear along the fence.
- `Boundary Road Block Offset`: controls how far road blocks sit away from the fence line.
- `Site Ground Roughness`: controls low-amplitude uneven terrain height when `Create Uneven Site Ground` is enabled.
- `Site Ground Noise Scale`: controls the size of broad terrain undulations.
- `Debug Exaggerate Uneven Ground`: temporarily exaggerates terrain roughness so the generated mesh shape is easy to inspect.

## ML Dataset Export

The current Unity scene JSONs already contain useful supervision for a future ML/DL layer:

- source facility labels and layout context
- selected prefab or compound asset targets
- support and functional anchors
- relative object placement offsets
- scene validation status

Export the compiled scenes into JSONL training records with:

```powershell
python .\scripts\export_ml_dataset.py
```

This writes:

- `output/ml_dataset/asset_selection.jsonl`: examples for semantic asset selection
- `output/ml_dataset/relation_placement.jsonl`: Pair2Scene-style dependent/anchor placement tuples
- `output/ml_dataset/scene_realism.jsonl`: scene-level validation and plausibility summaries
- `output/ml_dataset/manifest.json`: record counts and source scene list

The first practical ML task should be a lightweight baseline over these records, not full end-to-end scene generation. Good initial targets are:

- predict `prefab_name` from facility type, dimensions, site context, and source kind
- predict relative `x/z/yaw` offsets from dependent-anchor pairs
- rank generated seed variants using validation status and future manual accept/reject labels

Run the dependency-free baseline models with:

```powershell
python .\scripts\train_ml_baselines.py
```

This writes:

- `output/ml_baselines/asset_selection_baseline.json`: most-common prefab predictor by source/facility/category
- `output/ml_baselines/relation_placement_baseline.json`: mean relative pose predictor by dependent-anchor relation
- `output/ml_baselines/metrics.json`: train/test metrics by held-out scene

These baselines are intentionally simple. They are meant to show whether the generated records contain learnable signal before adding PyTorch models.

To run the full first-iteration pipeline over a folder of optimized layouts:

```powershell
python .\scripts\run_first_ml_iteration.py --input-dir .\data --safe-only --seeds 0 1 2 --clean --output-root .\output\first_ml_iteration_safe
```

This compiles scene variants, exports ML records, trains the baselines, and writes:

- `output/first_ml_iteration_safe/scenes/`
- `output/first_ml_iteration_safe/ml_dataset/`
- `output/first_ml_iteration_safe/ml_baselines/`
- `output/first_ml_iteration_safe/iteration_report.json`

After tightening accessory placement validation, the filtered first iteration can be run with:

```powershell
python .\scripts\run_first_ml_iteration.py --input-dir .\data --safe-only --seeds 0 1 2 --clean --output-root .\output\first_ml_iteration_safe_filtered
python .\scripts\train_scene_realism_mlp.py --dataset-dir .\output\first_ml_iteration_safe_filtered\ml_dataset --output-dir .\models\scene_realism_mlp
```

The `train_scene_realism_mlp.py` model is a small PyTorch classifier that predicts whether a generated scene needs review. It uses scene-summary and geometry-summary features, so treat it as a hybrid learned validation/scoring module rather than an image-understanding model.

For the first zone-context asset-selection model:

```powershell
python .\scripts\export_zone_asset_dataset.py
python .\scripts\train_zone_asset_mlp.py --epochs 100
python .\scripts\predict_zone_assets.py .\output\first_ml_iteration_safe_filtered\scenes\cslpelite_layout_000_seed_000_unity_scene.json --limit 5
```

This trains a multi-label PyTorch model:

```text
zone specification + nearby-zone context -> set of likely assets/prefabs
```

This is the first concrete step toward learned construction-site scene understanding. It learns what assets belong to each zone type before we ask a second model to predict exact relative placement.

For the first relation-aware placement model:

```powershell
python .\scripts\export_zone_asset_placement_dataset.py
python .\scripts\train_zone_asset_placement_mlp.py --source-kind accessory --epochs 70 --output-dir .\models\zone_asset_placement_mlp_accessory
python .\scripts\predict_zone_asset_placements.py .\output\first_ml_iteration_safe_filtered\scenes\cslpelite_layout_000_seed_000_unity_scene.json --limit 10
```

This trains:

```text
zone specification + selected asset + nearby-zone context -> relative x/z/yaw placement
```

Use the accessory-only model first. Rule-scatter records are intentionally random and should later be modelled as a stochastic distribution rather than a single deterministic regression target.

To generate a first hybrid ML-guided Unity scene:

```powershell
python .\scripts\generate_ml_guided_scene.py .\examples\bulleen_layout.json -o .\output\bulleen_layout_ml_guided_unity_scene.json --scatter-seed 0
python .\scripts\generate_ml_guided_scene.py .\examples\standard_layout_021.json -o .\output\standard_layout_021_ml_guided_unity_scene.json --scatter-seed 0
```

This keeps primary optimized facilities fixed, uses the zone asset model to propose extra accessories, and uses the accessory placement model to predict relative `x/z/yaw` around each zone. Predicted objects or moves are kept only when the normal boundary, entrance, exclusion, and overlap checks pass.

ML-guided asset proposals are also passed through a facility-type semantic compatibility filter. For example, office/site-admin zones are limited to access/safety/support props such as cones, barrels, floodlight stands, and generators; storage-like piles, planks, pipes, and work clutter are reserved for storage/core zones.

Scene enrichment uses constrained randomness. Small repeatable props such as cones, barrels, pallets, concrete bags, and concrete bricks may appear either individually or in small nearby clusters. Larger or context-sensitive equipment is restricted more heavily; for example, standalone construction lifts and the currently uncalibrated `SM_Stock01_2` stack are not used as random scatter.

Repeated labelled zones now receive visual variants while preserving the optimized layout position. Cores cycle through curated compound assemblies; offices cycle through complete cargo-container variants; rest areas mix toilet/service-container treatments; storage zones cycle through pipe, tarp, rebar, and material-bay treatments with different accessory/fence arrangements.

Storage-zone local bay boundaries use low road-block barriers rather than tall fence panels, because they read better as temporary material-yard dividers. The site perimeter boundary fence is still generated separately by the Unity importer.

For the current trained models, `examples/bulleen_layout.json` is the better visual test case. `examples/standard_layout_021.json` is much smaller than the training layouts, so the guardrails may reject most ML placements and fall back toward the rule-based output.

Unity test flow:

1. Copy the generated JSON into `Assets/StreamingAssets` in the Unity project.
2. Select the `SceneImporter` object.
3. Drag the ML-guided JSON into `Scene Json Asset`, or set `Streaming Assets Json` to the file name.
4. Click `Import Scene JSON`.
5. Compare the ML-guided scene against the previous rule-based `bulleen_layout_unity_scene.json`.

To generate many Unity scenes from optimized layouts in `data/`, use the batch generator:

```powershell
# Quick smoke test
python .\scripts\batch_generate_unity_scenes.py --safe-only --limit 5 --mode ml_guided --seeds 0 --output-root .\output\batch_smoke_ml_guided

# Production pass over all safe optimization layouts
python .\scripts\batch_generate_unity_scenes.py --safe-only --mode ml_guided --seeds 0 --output-root .\output\batch_safe_ml_guided

# Optional: generate both rule-based and ML-guided scenes for comparison
python .\scripts\batch_generate_unity_scenes.py --safe-only --mode rule ml_guided --seeds 0 --output-root .\output\batch_safe_compare
```

The batch generator writes Unity scene JSONs into `scenes/`, plus:

- `batch_report.json`: validation counts, failures, output locations
- `scene_records.jsonl`: one record per generated scene with object counts, validation status, and ML acceptance/rejection statistics

Layouts not marked `feasibility.safe=true` can also be generated by omitting `--safe-only`, but those should be treated as review/debug scenes because the source optimization result may already violate layout constraints.

The current ML-guided commands load trained models from `models/` by default. Older first-iteration folders under `output/` are kept as experiment history only and are not required for normal scene generation.

## Project Structure

```text
config/
  asset_catalog.json        # semantic type -> prefab candidates
  asset_catalog.generated.json # catalog generated from the Unity asset inventory
  facility_defaults.json    # default dimensions, clearances, relation policies
scripts/
  build_asset_catalog.py    # Unity prefab inventory -> semantic catalog
  layout_to_scene.py        # raw layout -> relation-aware 3D scene compiler and rule-based scatter
  generate_ml_guided_scene.py # hybrid ML asset proposal + accessory placement scene generator
  batch_generate_unity_scenes.py # batch raw layouts -> Unity scene JSONs + validation report
  analyze_asset_kits.py     # diagnostic grouping for exploded prefab kits
models/
  zone_asset_mlp/           # trained zone-context -> accessory asset proposal model
  zone_asset_placement_mlp_accessory/ # trained zone-context -> accessory offset/yaw model
  scene_realism_mlp/        # optional generated-scene review classifier
unity/
  ConstructionSceneImporter.cs # Unity editor importer for generated scene JSON
output/
  batch_safe_ml_guided/     # current production batch output for Unity testing
  *_scene.json              # latest single-layout test scene graphs
```

## Cleanup Policy

The project was hard-cleaned after the first successful milestone. Keep the active path small:

1. Source layouts come from `data/` or directly from the CEXO result folder.
2. Scene logic lives in `scripts/`, `config/`, `models/`, and `unity/`.
3. Current Unity-test outputs live in `output/batch_safe_ml_guided/` and the latest single-layout JSONs.
4. Large smoke-test and first-iteration output folders were deleted. Regenerate them only when running a new experiment.

## Current Assumptions

- Raw `x` and `y` are normalized layout coordinates.
- 3D world coordinates use `x` and `z` horizontally, with `y` as height.
- Most construction facilities are ground-supported.
- `examples/bulleen_layout.json` supplies site dimensions, dimensions, rotation, boundary, and exclusions.
- `examples/standard_layout_021.json` omits dimensions and site size, so compiler defaults are used.
- Functional relations are inferred from facility type:
  - crane -> nearest core
  - core -> nearest crane or entrance
  - storage -> nearest crane or core
  - office -> nearest entrance
  - rest area -> nearest office or entrance

## Next Implementation Steps

1. Review rule-based scatter in Unity and tune counts/radius rules where it feels too dense or too sparse.
2. Replace simple road polygons with richer road/decal placement where prefab scale is known.
3. Enforce exclusion-zone polygon overlap, not only center-point checks.
4. Add oriented bounding-box collision checks.
5. Add Unity terrain height/slope snapping for scatter objects if a non-flat terrain is introduced.
