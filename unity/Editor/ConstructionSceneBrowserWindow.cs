#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public class ConstructionSceneBrowserWindow : EditorWindow
{
    private const string LastFolderKey = "CEXOToUnity.SceneBrowser.LastFolder";

    private string sceneFolder;
    private string filterText = "";
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
        importer = FindImporterInScene();
        if (!string.IsNullOrEmpty(sceneFolder) && Directory.Exists(sceneFolder))
        {
            RefreshSceneList();
        }
    }

    private void OnGUI()
    {
        EditorGUILayout.LabelField("Generated Scene Folder", EditorStyles.boldLabel);
        using (new EditorGUILayout.HorizontalScope())
        {
            EditorGUILayout.SelectableLabel(string.IsNullOrEmpty(sceneFolder) ? "<none selected>" : sceneFolder, GUILayout.Height(EditorGUIUtility.singleLineHeight));
            if (GUILayout.Button("Browse", GUILayout.Width(90f)))
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
        }

        EditorGUILayout.Space(8f);
        importer = (ConstructionSceneImporter)EditorGUILayout.ObjectField("Scene Importer", importer, typeof(ConstructionSceneImporter), true);
        using (new EditorGUILayout.HorizontalScope())
        {
            if (GUILayout.Button("Find/Create Importer", GUILayout.Width(150f)))
            {
                importer = FindOrCreateImporter();
                Selection.activeObject = importer.gameObject;
            }

            GUI.enabled = importer != null && selectedIndex >= 0 && selectedIndex < FilteredPaths().Count;
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

    private void RefreshSceneList()
    {
        sceneJsonPaths.Clear();
        if (string.IsNullOrEmpty(sceneFolder) || !Directory.Exists(sceneFolder))
        {
            return;
        }

        sceneJsonPaths.AddRange(Directory.GetFiles(sceneFolder, "*.json", SearchOption.TopDirectoryOnly));
        sceneJsonPaths.Sort(StringComparer.OrdinalIgnoreCase);
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

        importer = importer != null ? importer : FindOrCreateImporter();
        if (importer == null)
        {
            Debug.LogError("No ConstructionSceneImporter could be found or created.");
            return;
        }

        string selectedPath = sceneJsonPaths[selectedIndex];
        Undo.RecordObject(importer, "Import Generated Construction Scene");
        importer.externalSceneJsonPath = selectedPath;
        importer.sceneJsonAsset = null;
        importer.ImportScene();
        EditorUtility.SetDirty(importer);
        Selection.activeObject = importer.gameObject;
    }
}
#endif
