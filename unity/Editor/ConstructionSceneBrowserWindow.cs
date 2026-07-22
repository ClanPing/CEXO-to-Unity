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
    private string statusMessage = "Select a generated scene folder, then click a scene to import it.";

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
                statusMessage = $"Using importer: {importer.name}";
            }

            GUI.enabled = IsSelectionValid();
            if (GUILayout.Button("Reimport Selected Scene"))
            {
                ImportSelectedScene();
            }
            GUI.enabled = true;
        }

        EditorGUILayout.Space(8f);
        using (EditorGUI.ChangeCheckScope check = new EditorGUI.ChangeCheckScope())
        {
            filterText = EditorGUILayout.TextField("Filter", filterText);
            if (check.changed)
            {
                ClampSelectionToVisibleList();
            }
        }

        List<string> visiblePaths = FilteredPaths();
        EditorGUILayout.LabelField($"{visiblePaths.Count} scene JSON files shown / {sceneJsonPaths.Count} found");

        DrawSelectedScenePanel(visiblePaths);

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
                    SelectScene(IndexInFullList(path), true);
                }

                if (GUILayout.Button("Replace", GUILayout.Width(80f)))
                {
                    SelectScene(IndexInFullList(path), true);
                }
            }
        }
        EditorGUILayout.EndScrollView();

        EditorGUILayout.Space(6f);
        EditorGUILayout.HelpBox(statusMessage, MessageType.Info);
    }

    private void RefreshSceneList()
    {
        sceneJsonPaths.Clear();
        if (string.IsNullOrEmpty(sceneFolder) || !Directory.Exists(sceneFolder))
        {
            statusMessage = "Scene folder is not set or no longer exists.";
            return;
        }

        sceneJsonPaths.AddRange(Directory.GetFiles(sceneFolder, "*.json", SearchOption.TopDirectoryOnly));
        sceneJsonPaths.Sort(StringComparer.OrdinalIgnoreCase);
        ClampSelectionToVisibleList();
        statusMessage = $"Found {sceneJsonPaths.Count} generated scene JSON files.";
    }

    private void DrawSelectedScenePanel(List<string> visiblePaths)
    {
        EditorGUILayout.Space(8f);
        EditorGUILayout.LabelField("Selected Scene", EditorStyles.boldLabel);

        string selectedPath = IsSelectionValid() ? sceneJsonPaths[selectedIndex] : "";
        EditorGUILayout.SelectableLabel(string.IsNullOrEmpty(selectedPath) ? "<none selected>" : Path.GetFileName(selectedPath), EditorStyles.helpBox, GUILayout.Height(24f));

        using (new EditorGUILayout.HorizontalScope())
        {
            GUI.enabled = visiblePaths.Count > 0;
            if (GUILayout.Button("Previous Scene", GUILayout.Width(120f)))
            {
                SelectRelativeVisibleScene(visiblePaths, -1);
            }

            if (GUILayout.Button("Next Scene", GUILayout.Width(120f)))
            {
                SelectRelativeVisibleScene(visiblePaths, 1);
            }
            GUI.enabled = true;

            GUILayout.FlexibleSpace();
            GUI.enabled = IsSelectionValid();
            if (GUILayout.Button("Reveal JSON", GUILayout.Width(100f)))
            {
                EditorUtility.RevealInFinder(sceneJsonPaths[selectedIndex]);
            }
            GUI.enabled = true;
        }
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

    private bool IsSelectionValid()
    {
        return selectedIndex >= 0 && selectedIndex < sceneJsonPaths.Count;
    }

    private void ClampSelectionToVisibleList()
    {
        List<string> visiblePaths = FilteredPaths();
        if (visiblePaths.Count == 0)
        {
            selectedIndex = -1;
            return;
        }

        if (!IsSelectionValid() || !visiblePaths.Contains(sceneJsonPaths[selectedIndex]))
        {
            selectedIndex = IndexInFullList(visiblePaths[0]);
        }
    }

    private void SelectScene(int index, bool importAfterSelection)
    {
        if (index < 0 || index >= sceneJsonPaths.Count)
        {
            return;
        }

        selectedIndex = index;
        statusMessage = $"Selected {Path.GetFileName(sceneJsonPaths[selectedIndex])}";
        if (importAfterSelection)
        {
            ImportSelectedScene();
        }
    }

    private void SelectRelativeVisibleScene(List<string> visiblePaths, int direction)
    {
        if (visiblePaths.Count == 0)
        {
            selectedIndex = -1;
            return;
        }

        int visibleIndex = IsSelectionValid() ? visiblePaths.IndexOf(sceneJsonPaths[selectedIndex]) : -1;
        int nextVisibleIndex = visibleIndex < 0 ? 0 : Mathf.Clamp(visibleIndex + direction, 0, visiblePaths.Count - 1);
        SelectScene(IndexInFullList(visiblePaths[nextVisibleIndex]), true);
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
        statusMessage = $"Imported {Path.GetFileName(selectedPath)}";
    }
}
#endif
