# CEXO to Unity Importer

This folder is the Unity package source for previewing CEXO-generated construction scenes.

## What Users Import

The Unity importer consumes the Stage 2 Unity scene JSON, not the raw Stage 1 layout JSON.

Typical Streamlit output path:

```text
output/streamlit_combined_runs/<run_name>/unity_scenes/scenes/*_unity_scene.json
```

Current verified Bulleen example:

```text
output/streamlit_combined_runs/<run_name>/unity_scenes/scenes/cslpelite_layout_000_seed_042_ml_guided_unity_scene.json
```

The matching run report is:

```text
output/streamlit_combined_runs/<run_name>/unity_scenes/batch_report.json
```

## Package Contents

- `ConstructionSceneImporter.cs`: runtime/editor-safe importer component.
- `Editor/ConstructionSceneBrowserWindow.cs`: Unity menu window for browsing generated scene JSON files.
- `StreamingAssets/cexo_asset_catalog.json`: editable prefab path remapping catalog.
- `StreamingAssets/demo_standard_unity_scene.json`: small standard-case demo scene JSON.
- `StreamingAssets/demo_bulleen_unity_scene.json`: Bulleen-case demo scene JSON.

## Unity Usage

1. Install the required construction prefabs in the Unity project.
2. Import this package/folder into Unity.
3. Open `Tools > CEXO to Unity > Scene Browser`.
4. Click `Import Scene JSON...` to load one downloaded Unity scene JSON directly,
   or click `Browse Folder` under `Generated Scene Folder` to load a catalogue
   of generated scenes.
5. Optionally select an `Asset Catalog JSON`.
6. Click `Import` beside the desired scene.

The importer automatically clears the previous generated scene and loads the
new JSON in the same action when `Clear Existing Generated Objects` is enabled.
Use `Clear Generated Scene` only when you want to remove the current preview
without importing another JSON.

The scene browser remembers the last generated scene folder using Unity Editor
preferences. When the window is reopened, it scans that remembered folder and
shows files matching `*_unity_scene*.json`. Use `Clear` beside the folder if you
want the browser to start empty again.

## Asset Catalog

By default, generated scene JSONs contain prefab paths for the SilverTM Construction Site asset pack:

```text
Assets/ConstructionSite/Prefab/...
```

If users do not own that asset pack, they can still use the importer in two ways:

- Leave missing paths as-is: the importer creates placeholder cubes for missing prefabs.
- Edit `cexo_asset_catalog.json`: map generated prefab names or `source_path` values to prefabs that exist in their own Unity project.

For a single prefab replacement:

```json
{
  "name": "SM_CargoContainer02",
  "source_path": "Assets/ConstructionSite/Prefab/ConstructionSite/SM_CargoContainer02.prefab",
  "path": "Assets/MyAssets/Prefabs/MyOfficeContainer.prefab",
  "assembly_type": "single_prefab"
}
```

For compound objects such as cranes or cores:

- Set `path` to a single prefab to replace the whole assembly.
- Leave `path` empty and provide `children` to define a multi-prefab assembly.
- Leave both empty to use the children embedded in the generated scene JSON.

## External Asset Dependency

This repository should not redistribute paid/commercial Unity Asset Store content. The tested prefab paths correspond to:

```text
Construction Site SilverTM
https://assetstore.unity.com/packages/3d/environments/industrial/construction-site-silvertm-154967
```

Users may install that pack, or map the catalog to their own compatible construction assets.
