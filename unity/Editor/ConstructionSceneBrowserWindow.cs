#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace CEXOToUnity
{

public class ConstructionSceneBrowserWindow : EditorWindow
{
    private const string LastFolderKey = "CEXOToUnity.SceneBrowser.LastFolder";
    private const string LastCatalogKey = "CEXOToUnity.SceneBrowser.LastCatalog";

    private string sceneFolder;
    private string assetCatalogPath;
    private string filterText = "";
    private string statusMessage = "";
    private readonly List<string> sceneJsonPaths = new List<string>();
    private Vector2 scrollPosition;
    private int selectedIndex = -1;
    private ConstructionSceneImporter importer;

    [MenuItem("Tools/CEXO to Unity/Scene Browser")]
    public static void Open()
    {
        ConstructionSceneBrowserWindow window = GetWindow<ConstructionSceneBrowserWindow>("CEXO Scene Browser");
        window.minSize = new Vector2(620f, 420f);
        window.Show();
    }

    private void OnEnable()
    {
        sceneFolder = EditorPrefs.GetString(LastFolderKey, "");
        assetCatalogPath = EditorPrefs.GetString(LastCatalogKey, "");
        importer = FindImporterInScene();
        if (!string.IsNullOrEmpty(sceneFolder) && Directory.Exists(sceneFolder))
        {
            RefreshSceneList();
        }
    }

    private void OnGUI()
    {
        DrawDirectImportControls();
        EditorGUILayout.Space(10f);

        EditorGUILayout.LabelField("Generated Scene Folder", EditorStyles.boldLabel);
        using (new EditorGUILayout.HorizontalScope())
        {
            EditorGUILayout.SelectableLabel(string.IsNullOrEmpty(sceneFolder) ? "<none selected>" : sceneFolder, GUILayout.Height(EditorGUIUtility.singleLineHeight));
            if (GUILayout.Button("Browse Folder", GUILayout.Width(110f)))
            {
                string startFolder = Directory.Exists(sceneFolder) ? sceneFolder : Application.dataPath;
                string chosenFolder = EditorUtility.OpenFolderPanel("Select Generated Scene JSON Folder", startFolder, "");
                if (!string.IsNullOrEmpty(chosenFolder))
                {
                    sceneFolder = chosenFolder;
                    EditorPrefs.SetString(LastFolderKey, sceneFolder);
                    selectedIndex = -1;
                    RefreshSceneList();
                }
            }

            if (GUILayout.Button("Refresh", GUILayout.Width(90f)))
            {
                RefreshSceneList();
            }

            if (GUILayout.Button("Clear", GUILayout.Width(70f)))
            {
                sceneFolder = "";
                selectedIndex = -1;
                sceneJsonPaths.Clear();
                EditorPrefs.DeleteKey(LastFolderKey);
                statusMessage = "Cleared remembered generated scene folder.";
            }
        }

        EditorGUILayout.Space(8f);
        EditorGUILayout.LabelField("Asset Catalog JSON", EditorStyles.boldLabel);
        using (new EditorGUILayout.HorizontalScope())
        {
            EditorGUILayout.SelectableLabel(string.IsNullOrEmpty(assetCatalogPath) ? "<optional>" : assetCatalogPath, GUILayout.Height(EditorGUIUtility.singleLineHeight));
            if (GUILayout.Button("Browse", GUILayout.Width(90f)))
            {
                string startFolder = File.Exists(assetCatalogPath) ? Path.GetDirectoryName(assetCatalogPath) : Application.dataPath;
                string chosenPath = EditorUtility.OpenFilePanel("Select Asset Catalog JSON", startFolder, "json");
                if (!string.IsNullOrEmpty(chosenPath))
                {
                    assetCatalogPath = chosenPath;
                    EditorPrefs.SetString(LastCatalogKey, assetCatalogPath);
                }
            }

            if (GUILayout.Button("Clear", GUILayout.Width(90f)))
            {
                assetCatalogPath = "";
                EditorPrefs.DeleteKey(LastCatalogKey);
            }
        }

        EditorGUILayout.Space(8f);
        DrawImporterControls();

        EditorGUILayout.Space(8f);
        using (new EditorGUILayout.HorizontalScope())
        {
            GUI.enabled = selectedIndex >= 0 && selectedIndex < sceneJsonPaths.Count;
            if (GUILayout.Button("Import Selected Scene"))
            {
                ImportSelectedScene();
            }
            GUI.enabled = true;
        }

        EditorGUILayout.Space(8f);
        filterText = EditorGUILayout.TextField("Filter", filterText);
        List<string> visiblePaths = FilteredPaths();
        EditorGUILayout.LabelField($"{visiblePaths.Count} scene JSON files shown / {sceneJsonPaths.Count} found");
        if (!string.IsNullOrEmpty(statusMessage))
        {
            EditorGUILayout.HelpBox(statusMessage, MessageType.Info);
        }

        EditorGUILayout.Space(4f);
        scrollPosition = EditorGUILayout.BeginScrollView(scrollPosition);
        for (int i = 0; i < visiblePaths.Count; i++)
        {
            string path = visiblePaths[i];
            bool selected = selectedIndex == IndexInFullList(path);
            GUIStyle style = selected ? EditorStyles.helpBox : EditorStyles.label;

            using (new EditorGUILayout.HorizontalScope(style))
            {
                if (GUILayout.Button(Path.GetFileName(path), EditorStyles.label))
                {
                    selectedIndex = IndexInFullList(path);
                }

                if (GUILayout.Button("Import", GUILayout.Width(70f)))
                {
                    selectedIndex = IndexInFullList(path);
                    ImportSelectedScene();
                }
            }
        }
        EditorGUILayout.EndScrollView();
    }

    private void DrawDirectImportControls()
    {
        EditorGUILayout.LabelField("Import Unity Scene JSON", EditorStyles.boldLabel);
        using (new EditorGUILayout.HorizontalScope())
        {
            if (GUILayout.Button("Import Scene JSON...", GUILayout.Height(26f)))
            {
                string startFolder = Directory.Exists(sceneFolder) ? sceneFolder : Application.dataPath;
                string chosenPath = EditorUtility.OpenFilePanel("Import Unity Scene JSON", startFolder, "json");
                if (!string.IsNullOrEmpty(chosenPath))
                {
                    ImportSceneJsonPath(chosenPath);
                }
            }

            if (GUILayout.Button("Clear Generated Scene", GUILayout.Width(160f), GUILayout.Height(26f)))
            {
                ClearGeneratedScene();
            }
        }
    }

    private void DrawImporterControls()
    {
        importer = importer != null ? importer : FindImporterInScene();
        string importerLabel = importer != null
            ? $"Using: {importer.gameObject.name}"
            : "Importer will be created automatically on import.";

        EditorGUILayout.LabelField("Scene Importer", EditorStyles.boldLabel);
        using (new EditorGUILayout.HorizontalScope())
        {
            EditorGUILayout.LabelField(importerLabel);
            if (GUILayout.Button("Find/Create", GUILayout.Width(100f)))
            {
                importer = FindOrCreateImporter();
                Selection.activeObject = importer.gameObject;
                statusMessage = $"Ready: {importer.gameObject.name}.";
            }

            GUI.enabled = importer != null;
            if (GUILayout.Button("Select", GUILayout.Width(70f)))
            {
                Selection.activeObject = importer.gameObject;
            }
            GUI.enabled = true;
        }
    }

    private void RefreshSceneList()
    {
        sceneJsonPaths.Clear();
        if (string.IsNullOrEmpty(sceneFolder) || !Directory.Exists(sceneFolder))
        {
            return;
        }

        sceneJsonPaths.AddRange(Directory.GetFiles(sceneFolder, "*_unity_scene*.json", SearchOption.TopDirectoryOnly));
        sceneJsonPaths.Sort(StringComparer.OrdinalIgnoreCase);
        statusMessage = $"Scanned {sceneFolder}. The browser shows Unity-ready scene JSON files only.";
    }

    private List<string> FilteredPaths()
    {
        if (string.IsNullOrWhiteSpace(filterText))
        {
            return new List<string>(sceneJsonPaths);
        }

        string normalizedFilter = filterText.Trim();
        List<string> filtered = new List<string>();
        foreach (string path in sceneJsonPaths)
        {
            if (Path.GetFileName(path).IndexOf(normalizedFilter, StringComparison.OrdinalIgnoreCase) >= 0)
            {
                filtered.Add(path);
            }
        }

        return filtered;
    }

    private int IndexInFullList(string path)
    {
        return sceneJsonPaths.IndexOf(path);
    }

    private ConstructionSceneImporter FindOrCreateImporter()
    {
        ConstructionSceneImporter existing = FindImporterInScene();
        if (existing != null)
        {
            return existing;
        }

        GameObject importerObject = new GameObject("SceneImporter");
        Undo.RegisterCreatedObjectUndo(importerObject, "Create Construction Scene Importer");
        return importerObject.AddComponent<ConstructionSceneImporter>();
    }

    private ConstructionSceneImporter FindImporterInScene()
    {
#if UNITY_2023_1_OR_NEWER
        return UnityEngine.Object.FindFirstObjectByType<ConstructionSceneImporter>();
#else
        return UnityEngine.Object.FindObjectOfType<ConstructionSceneImporter>();
#endif
    }

    private void ImportSelectedScene()
    {
        if (selectedIndex < 0 || selectedIndex >= sceneJsonPaths.Count)
        {
            Debug.LogWarning("No generated scene JSON selected.");
            return;
        }

        string selectedPath = sceneJsonPaths[selectedIndex];
        ImportSceneJsonPath(selectedPath);
    }

    private void ImportSceneJsonPath(string selectedPath)
    {
        if (string.IsNullOrEmpty(selectedPath) || !File.Exists(selectedPath))
        {
            Debug.LogWarning($"Scene JSON path does not exist: {selectedPath}");
            statusMessage = "Selected scene JSON path does not exist.";
            return;
        }

        importer = importer != null ? importer : FindOrCreateImporter();
        if (importer == null)
        {
            Debug.LogError("No ConstructionSceneImporter could be found or created.");
            statusMessage = "No ConstructionSceneImporter could be found or created.";
            return;
        }

        Undo.RecordObject(importer, "Import Generated Construction Scene");
        importer.externalSceneJsonPath = selectedPath;
        importer.sceneJsonAsset = null;
        importer.externalAssetCatalogPath = assetCatalogPath;
        importer.assetCatalogAsset = null;
        importer.ImportScene();
        EditorUtility.SetDirty(importer);
        Selection.activeObject = importer.gameObject;
        statusMessage = $"Imported {Path.GetFileName(selectedPath)}.";
    }

    private void ClearGeneratedScene()
    {
        importer = importer != null ? importer : FindOrCreateImporter();
        if (importer == null)
        {
            Debug.LogError("No ConstructionSceneImporter could be found or created.");
            statusMessage = "No ConstructionSceneImporter could be found or created.";
            return;
        }

        Undo.RecordObject(importer, "Clear Generated Construction Scene");
        importer.ClearGeneratedScene();
        EditorUtility.SetDirty(importer);
        Selection.activeObject = importer.gameObject;
        statusMessage = "Cleared generated scene.";
    }
}

}
#endif
