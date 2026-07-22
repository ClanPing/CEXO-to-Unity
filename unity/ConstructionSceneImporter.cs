using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

#if UNITY_EDITOR
using UnityEditor;
#endif

[Serializable]
public class ConstructionSceneData
{
    public string scene_id;
    public SiteData site;
    public SiteVisualsData site_visuals;
    public List<SceneObjectData> objects;
}

[Serializable]
public class SiteData
{
    public float ground_y;
    public SiteBoundsData bounds;
}

[Serializable]
public class SiteBoundsData
{
    public float min_x;
    public float max_x;
    public float min_z;
    public float max_z;
}

[Serializable]
public class SiteVisualsData
{
    public List<Vector3Json> boundary_points;
    public List<RoadZoneData> road_zones;
    public List<EntranceMarkerData> entrances;
}

[Serializable]
public class RoadZoneData
{
    public string id;
    public List<Vector3Json> polygon_points;
}

[Serializable]
public class EntranceMarkerData
{
    public string id;
    public Vector3Json position;
}

[Serializable]
public class SceneObjectData
{
    public string id;
    public PrefabData prefab;
    public PlacementData placement;
    public TransformData transform;
    public AnchorData anchors;
}

[Serializable]
public class PrefabData
{
    public string name;
    public string path;
    public string construction_class;
    public string assembly_type;
    public List<PrefabChildData> children;
}

[Serializable]
public class PrefabChildData
{
    public string name;
    public string path;
    public Vector3Json position;
    public Vector3Json rotation;
    public Vector3Json scale;
}

[Serializable]
public class PlacementData
{
    public string pivot_type;
    public bool snap_to_ground;
    public Vector3Json bbox_size;
    public Vector3Json prefab_bbox_size;
    public string scale_policy;
}

[Serializable]
public class TransformData
{
    public Vector3Json position;
    public Vector3Json rotation;
    public Vector3Json scale;
}

[Serializable]
public class AnchorData
{
    public string support_id;
    public string functional_id;
}

[Serializable]
public class Vector3Json
{
    public float x;
    public float y;
    public float z;

    public Vector3 ToVector3()
    {
        return new Vector3(x, y, z);
    }
}

public class ConstructionSceneImporter : MonoBehaviour
{
    [Header("Scene JSON")]
    [Tooltip("Optional absolute path to a generated scene JSON outside the Unity Assets folder. Used first when set.")]
    public string externalSceneJsonPath;
    [Tooltip("Drag a JSON asset here, for example a file from Assets/StreamingAssets. If External Scene Json Path is empty, this is used next.")]
    public UnityEngine.Object sceneJsonAsset;
    [Tooltip("Fallback JSON file name inside Assets/StreamingAssets.")]
    public string streamingAssetsJson = "standard_layout_021_unity_scene.json";

    [Header("Import Options")]
    public bool clearExistingGeneratedObjects = true;
    public bool scaleToLayoutFootprint = false;
    public bool createSiteGround = true;
    public bool createRoadSurfaces = true;
    public bool createBoundaryFence = true;
    public bool createEntranceMarkers = true;
    public bool usePrefabSiteContext = true;
    public bool createBoundaryRoadBlockClusters = true;
    public bool createEntranceRoadBlocks = false;
    public bool createFootprintMarkers = true;
    public bool snapRendererBoundsToGround = true;
    public bool createUnevenSiteGround = true;
    public string generatedRootName = "GeneratedConstructionScene";

    [Header("Uneven Ground")]
    public int siteGroundSubdivisions = 36;
    public float siteGroundRoughness = 0.18f;
    public float siteGroundNoiseScale = 0.055f;
    public bool debugExaggerateUnevenGround = false;

    [Header("Site Context Prefabs")]
    public string boundaryFencePrefabPath = "Assets/ConstructionSite/Prefab/Fence/SM_Fence05.prefab";
    public string entranceGatePrefabPath = "Assets/ConstructionSite/Prefab/Building/Door/SM_Gate01.prefab";
    public string entranceRoadBlockPrefabPath = "Assets/ConstructionSite/Prefab/Fence/SM_RoadBlock03.prefab";
    public string boundaryRoadBlockPrefabPath = "Assets/ConstructionSite/Prefab/Fence/SM_RoadBlock04.prefab";
    public float fenceModuleSpacing = 4.8f;
    public float entranceOpeningWidth = 5.6f;
    public bool createEntranceGatePanels = false;
    public int entranceGatePanelCount = 3;
    public float entranceGatePanelSpacing = 1.75f;
    public float entranceRoadBlockSideOffset = 3.4f;
    public float entranceRoadBlockDepthOffset = 1.2f;
    public float boundaryRoadBlockSpacing = 28.0f;
    public float boundaryRoadBlockOffset = 1.4f;

    private readonly Dictionary<string, GameObject> spawned = new Dictionary<string, GameObject>();

    [ContextMenu("Import Scene JSON")]
    public void ImportScene()
    {
        string jsonText = ResolveSceneJsonText(out string sourceName);
        if (string.IsNullOrEmpty(jsonText))
        {
            Debug.LogError($"Scene JSON not found. External path '{externalSceneJsonPath}', asset '{(sceneJsonAsset != null ? sceneJsonAsset.name : "<none>")}', StreamingAssets '{streamingAssetsJson}'. {DescribeStreamingAssets()}");
            return;
        }

        ConstructionSceneData scene = JsonUtility.FromJson<ConstructionSceneData>(jsonText);
        if (scene == null || scene.objects == null)
        {
            Debug.LogError("Scene JSON could not be parsed or contains no objects.");
            return;
        }

        if (clearExistingGeneratedObjects)
        {
            ClearExistingRoot();
        }

        GameObject root = new GameObject(generatedRootName);
        if (!string.IsNullOrEmpty(scene.scene_id))
        {
            root.name = $"{generatedRootName}_{scene.scene_id}";
        }
        spawned.Clear();
        float groundY = scene.site != null ? scene.site.ground_y : 0f;

        if (createSiteGround)
        {
            CreateSiteGround(scene, root.transform);
        }
        CreateSiteVisuals(scene, root.transform);

        foreach (SceneObjectData obj in scene.objects)
        {
            GameObject instance = InstantiateSceneObject(obj, root.transform);
            if (instance != null)
            {
                if (snapRendererBoundsToGround && obj.placement != null && obj.placement.snap_to_ground)
                {
                    SnapInstanceToGround(instance, groundY);
                }
                spawned[obj.id] = instance;
                if (createFootprintMarkers)
                {
                    CreateFootprintMarker(obj, root.transform);
                }
            }
        }

        Debug.Log($"Imported {spawned.Count} construction scene objects from {sourceName}.");
    }

    private void CreateSiteVisuals(ConstructionSceneData scene, Transform parent)
    {
        if (scene.site_visuals == null)
        {
            return;
        }

        float groundY = scene.site != null ? scene.site.ground_y : 0f;
        Transform contextRoot = new GameObject("site_context").transform;
        contextRoot.SetParent(parent);

        if (createRoadSurfaces && scene.site_visuals.road_zones != null)
        {
            Material roadMaterial = CreateColoredMaterial(new Color(0.08f, 0.08f, 0.075f, 1.0f));
            foreach (RoadZoneData road in scene.site_visuals.road_zones)
            {
                CreatePolygonMesh($"road_{road.id}", road.polygon_points, groundY + 0.025f, roadMaterial, contextRoot);
            }
        }

        if (createBoundaryFence && scene.site_visuals.boundary_points != null)
        {
            List<Vector3> entrancePositions = GetEntrancePositions(scene.site_visuals.entrances, groundY);
            GameObject fencePrefab = usePrefabSiteContext ? LoadPrefab(boundaryFencePrefabPath) : null;
            if (fencePrefab != null)
            {
                CreateBoundaryPrefabSegments(scene.site_visuals.boundary_points, groundY, fencePrefab, entrancePositions, contextRoot);
            }
            else
            {
                Material fenceMaterial = CreateColoredMaterial(new Color(0.85f, 0.72f, 0.34f, 1.0f));
                CreateBoundarySegments(scene.site_visuals.boundary_points, groundY, fenceMaterial, contextRoot);
            }

            if (createBoundaryRoadBlockClusters && usePrefabSiteContext)
            {
                GameObject boundaryBlockPrefab = LoadPrefab(boundaryRoadBlockPrefabPath);
                if (boundaryBlockPrefab != null)
                {
                    CreateBoundaryRoadBlockClusters(scene.site_visuals.boundary_points, groundY, boundaryBlockPrefab, entrancePositions, contextRoot);
                }
            }

        }

        if (createEntranceMarkers && scene.site_visuals.entrances != null)
        {
            GameObject gatePrefab = usePrefabSiteContext ? LoadPrefab(entranceGatePrefabPath) : null;
            GameObject roadBlockPrefab = usePrefabSiteContext ? LoadPrefab(entranceRoadBlockPrefabPath) : null;
            if (gatePrefab != null || roadBlockPrefab != null)
            {
                CreateEntrancePrefabs(scene.site_visuals.entrances, scene.site_visuals.boundary_points, groundY, gatePrefab, roadBlockPrefab, contextRoot);
            }
            else
            {
                Material entranceMaterial = CreateColoredMaterial(new Color(0.1f, 0.85f, 0.25f, 1.0f));
                foreach (EntranceMarkerData entrance in scene.site_visuals.entrances)
                {
                    if (entrance.position == null)
                    {
                        continue;
                    }
                    GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
                    marker.name = $"entrance_{entrance.id}";
                    marker.transform.SetParent(contextRoot);
                    Vector3 position = entrance.position.ToVector3();
                    marker.transform.position = new Vector3(position.x, groundY + 1.0f, position.z);
                    marker.transform.localScale = new Vector3(2.5f, 2.0f, 2.5f);
                    Renderer renderer = marker.GetComponent<Renderer>();
                    if (renderer != null)
                    {
                        renderer.sharedMaterial = entranceMaterial;
                    }
                }
            }
        }
    }

    private List<Vector3> GetEntrancePositions(List<EntranceMarkerData> entrances, float groundY)
    {
        List<Vector3> positions = new List<Vector3>();
        if (entrances == null)
        {
            return positions;
        }

        foreach (EntranceMarkerData entrance in entrances)
        {
            if (entrance.position == null)
            {
                continue;
            }
            Vector3 position = entrance.position.ToVector3();
            positions.Add(new Vector3(position.x, groundY, position.z));
        }
        return positions;
    }

    private string ResolveSceneJsonText(out string sourceName)
    {
        if (!string.IsNullOrWhiteSpace(externalSceneJsonPath))
        {
            string expandedPath = Environment.ExpandEnvironmentVariables(externalSceneJsonPath.Trim());
            sourceName = Path.GetFileName(expandedPath);
            if (File.Exists(expandedPath))
            {
                return File.ReadAllText(expandedPath);
            }

            Debug.LogError($"External scene JSON path does not exist: {expandedPath}");
            return null;
        }

        if (sceneJsonAsset != null)
        {
            sourceName = sceneJsonAsset.name;
            if (sceneJsonAsset is TextAsset textAsset)
            {
                return textAsset.text;
            }

#if UNITY_EDITOR
            string assetPath = AssetDatabase.GetAssetPath(sceneJsonAsset);
            if (!string.IsNullOrEmpty(assetPath))
            {
                string absolutePath = Path.Combine(Directory.GetCurrentDirectory(), assetPath);
                if (File.Exists(absolutePath))
                {
                    sourceName = Path.GetFileName(assetPath);
                    return File.ReadAllText(absolutePath);
                }
            }
#endif

            Debug.LogError($"Assigned Scene Json Asset is not readable as text: {sceneJsonAsset.name}");
            return null;
        }

        string path = ResolveSceneJsonPath();
        sourceName = Path.GetFileName(path);
        return File.Exists(path) ? File.ReadAllText(path) : null;
    }

    private void CreateSiteGround(ConstructionSceneData scene, Transform parent)
    {
        if (scene.site == null || scene.site.bounds == null)
        {
            return;
        }

        Material groundMaterial = CreateColoredMaterial(new Color(0.34f, 0.34f, 0.34f, 0.28f));
        float width = Mathf.Max(1f, scene.site.bounds.max_x - scene.site.bounds.min_x);
        float length = Mathf.Max(1f, scene.site.bounds.max_z - scene.site.bounds.min_z);
        float centerX = (scene.site.bounds.min_x + scene.site.bounds.max_x) * 0.5f;
        float centerZ = (scene.site.bounds.min_z + scene.site.bounds.max_z) * 0.5f;

        if (createUnevenSiteGround)
        {
            CreateUnevenSiteGroundMesh("site_ground", centerX, centerZ, width, length, scene.site.ground_y - 0.035f, groundMaterial, parent);
            return;
        }

        GameObject ground = GameObject.CreatePrimitive(PrimitiveType.Cube);
        ground.name = "site_ground";
        ground.transform.SetParent(parent);
        ground.transform.position = new Vector3(centerX, scene.site.ground_y - 0.03f, centerZ);
        ground.transform.localScale = new Vector3(width, 0.04f, length);

        Renderer renderer = ground.GetComponent<Renderer>();
        if (renderer != null)
        {
            renderer.sharedMaterial = groundMaterial;
        }
    }

    private void CreateUnevenSiteGroundMesh(
        string objectName,
        float centerX,
        float centerZ,
        float width,
        float length,
        float baseY,
        Material material,
        Transform parent)
    {
        int divisions = Mathf.Clamp(siteGroundSubdivisions, 4, 160);
        float roughness = Mathf.Max(0f, siteGroundRoughness) * (debugExaggerateUnevenGround ? 4f : 1f);
        float noiseScale = Mathf.Max(0.001f, siteGroundNoiseScale);
        int vertexCountPerSide = divisions + 1;

        Vector3[] vertices = new Vector3[vertexCountPerSide * vertexCountPerSide];
        Vector2[] uvs = new Vector2[vertices.Length];
        int[] triangles = new int[divisions * divisions * 6];

        float startX = centerX - width * 0.5f;
        float startZ = centerZ - length * 0.5f;
        for (int z = 0; z < vertexCountPerSide; z++)
        {
            float v = z / (float)divisions;
            for (int x = 0; x < vertexCountPerSide; x++)
            {
                float u = x / (float)divisions;
                float worldX = startX + width * u;
                float worldZ = startZ + length * v;
                float broadNoise = Mathf.PerlinNoise(worldX * noiseScale, worldZ * noiseScale) - 0.5f;
                float fineNoise = Mathf.PerlinNoise(worldX * noiseScale * 3.2f + 71.3f, worldZ * noiseScale * 3.2f + 19.7f) - 0.5f;
                float edgeFade = Mathf.SmoothStep(0f, 1f, Mathf.Min(Mathf.Min(u, 1f - u), Mathf.Min(v, 1f - v)) * 8f);
                float height = (broadNoise * 0.75f + fineNoise * 0.25f) * roughness * edgeFade;
                int index = z * vertexCountPerSide + x;
                vertices[index] = new Vector3(worldX, baseY + height, worldZ);
                uvs[index] = new Vector2(u, v);
            }
        }

        int triangleIndex = 0;
        for (int z = 0; z < divisions; z++)
        {
            for (int x = 0; x < divisions; x++)
            {
                int bottomLeft = z * vertexCountPerSide + x;
                int bottomRight = bottomLeft + 1;
                int topLeft = bottomLeft + vertexCountPerSide;
                int topRight = topLeft + 1;

                triangles[triangleIndex++] = bottomLeft;
                triangles[triangleIndex++] = topLeft;
                triangles[triangleIndex++] = topRight;
                triangles[triangleIndex++] = bottomLeft;
                triangles[triangleIndex++] = topRight;
                triangles[triangleIndex++] = bottomRight;
            }
        }

        Mesh mesh = new Mesh();
        mesh.name = objectName;
        mesh.vertices = vertices;
        mesh.uv = uvs;
        mesh.triangles = triangles;
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        GameObject ground = new GameObject(objectName);
        ground.transform.SetParent(parent);
        MeshFilter filter = ground.AddComponent<MeshFilter>();
        filter.sharedMesh = mesh;
        MeshRenderer renderer = ground.AddComponent<MeshRenderer>();
        renderer.sharedMaterial = material;
    }

    private void CreatePolygonMesh(string objectName, List<Vector3Json> points, float y, Material material, Transform parent)
    {
        if (points == null || points.Count < 3)
        {
            return;
        }

        GameObject polygonObject = new GameObject(objectName);
        polygonObject.transform.SetParent(parent);

        Vector3[] vertices = new Vector3[points.Count];
        for (int i = 0; i < points.Count; i++)
        {
            Vector3 point = points[i].ToVector3();
            vertices[i] = new Vector3(point.x, y, point.z);
        }

        Vector2[] uvs = new Vector2[points.Count];
        Bounds uvBounds = new Bounds(vertices[0], Vector3.zero);
        for (int i = 1; i < vertices.Length; i++)
        {
            uvBounds.Encapsulate(vertices[i]);
        }
        float uvWidth = Mathf.Max(1f, uvBounds.size.x);
        float uvLength = Mathf.Max(1f, uvBounds.size.z);
        for (int i = 0; i < vertices.Length; i++)
        {
            uvs[i] = new Vector2((vertices[i].x - uvBounds.min.x) / uvWidth, (vertices[i].z - uvBounds.min.z) / uvLength);
        }

        List<int> triangles = new List<int>();
        for (int i = 1; i < points.Count - 1; i++)
        {
            triangles.Add(0);
            triangles.Add(i);
            triangles.Add(i + 1);
            triangles.Add(0);
            triangles.Add(i + 1);
            triangles.Add(i);
        }

        Mesh mesh = new Mesh();
        mesh.name = objectName;
        mesh.vertices = vertices;
        mesh.uv = uvs;
        mesh.triangles = triangles.ToArray();
        mesh.RecalculateNormals();
        mesh.RecalculateBounds();

        MeshFilter filter = polygonObject.AddComponent<MeshFilter>();
        filter.sharedMesh = mesh;
        MeshRenderer renderer = polygonObject.AddComponent<MeshRenderer>();
        renderer.sharedMaterial = material;
    }

    private void CreateBoundarySegments(List<Vector3Json> points, float groundY, Material material, Transform parent)
    {
        if (points == null || points.Count < 2)
        {
            return;
        }

        for (int i = 0; i < points.Count; i++)
        {
            Vector3 start = points[i].ToVector3();
            Vector3 end = points[(i + 1) % points.Count].ToVector3();
            Vector3 delta = end - start;
            delta.y = 0f;
            float length = delta.magnitude;
            if (length < 0.1f)
            {
                continue;
            }

            GameObject segment = GameObject.CreatePrimitive(PrimitiveType.Cube);
            segment.name = $"boundary_fence_{i:00}";
            segment.transform.SetParent(parent);
            segment.transform.position = new Vector3((start.x + end.x) * 0.5f, groundY + 1.1f, (start.z + end.z) * 0.5f);
            segment.transform.rotation = Quaternion.Euler(0f, Mathf.Atan2(delta.x, delta.z) * Mathf.Rad2Deg, 0f);
            segment.transform.localScale = new Vector3(0.18f, 2.2f, length);

            Renderer renderer = segment.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.sharedMaterial = material;
            }
        }
    }

    private void CreateBoundaryPrefabSegments(List<Vector3Json> points, float groundY, GameObject fencePrefab, List<Vector3> entrancePositions, Transform parent)
    {
        if (points == null || points.Count < 2 || fencePrefab == null)
        {
            return;
        }

        float spacing = Mathf.Max(0.5f, fenceModuleSpacing);
        for (int i = 0; i < points.Count; i++)
        {
            Vector3 start = points[i].ToVector3();
            Vector3 end = points[(i + 1) % points.Count].ToVector3();
            start.y = groundY;
            end.y = groundY;

            Vector3 delta = end - start;
            delta.y = 0f;
            float length = delta.magnitude;
            if (length < 0.1f)
            {
                continue;
            }

            Vector3 direction = delta.normalized;
            int moduleCount = Mathf.Max(1, Mathf.CeilToInt(length / spacing));
            float actualSpacing = length / moduleCount;
            float yaw = Mathf.Atan2(direction.x, direction.z) * Mathf.Rad2Deg;

            for (int module = 0; module < moduleCount; module++)
            {
                float distanceAlong = Mathf.Min((module + 0.5f) * actualSpacing, length - 0.1f);
                Vector3 position = start + direction * distanceAlong;
                if (IsNearEntrance(position, entrancePositions))
                {
                    continue;
                }

                GameObject instance = Instantiate(fencePrefab, new Vector3(position.x, groundY, position.z), Quaternion.Euler(0f, yaw, 0f), parent);
                instance.name = $"boundary_fence_prefab_{i:00}_{module:00}";
                SnapInstanceToGround(instance, groundY);
            }
        }
    }

    private void CreateBoundaryRoadBlockClusters(List<Vector3Json> points, float groundY, GameObject roadBlockPrefab, List<Vector3> entrancePositions, Transform parent)
    {
        if (points == null || points.Count < 2 || roadBlockPrefab == null)
        {
            return;
        }

        float spacing = Mathf.Max(5f, boundaryRoadBlockSpacing);
        float sideOffset = Mathf.Max(0f, boundaryRoadBlockOffset);
        for (int i = 0; i < points.Count; i++)
        {
            Vector3 start = points[i].ToVector3();
            Vector3 end = points[(i + 1) % points.Count].ToVector3();
            start.y = groundY;
            end.y = groundY;

            Vector3 delta = end - start;
            delta.y = 0f;
            float length = delta.magnitude;
            if (length < spacing * 0.75f)
            {
                continue;
            }

            Vector3 direction = delta.normalized;
            Vector3 side = new Vector3(direction.z, 0f, -direction.x);
            int clusterCount = Mathf.Max(1, Mathf.FloorToInt(length / spacing));
            float yaw = Mathf.Atan2(direction.x, direction.z) * Mathf.Rad2Deg;

            for (int cluster = 0; cluster < clusterCount; cluster++)
            {
                float distanceAlong = Mathf.Min((cluster + 0.35f) * spacing, length - 0.1f);
                float sideSign = ((i + cluster) % 2 == 0) ? 1f : -1f;
                Vector3 basePosition = start + direction * distanceAlong;
                Vector3 position = basePosition + side * sideOffset * sideSign;

                if (IsNearEntrance(position, entrancePositions))
                {
                    continue;
                }

                GameObject block = Instantiate(roadBlockPrefab, new Vector3(position.x, groundY, position.z), Quaternion.Euler(0f, yaw, 0f), parent);
                block.name = $"boundary_roadblock_{i:00}_{cluster:00}";
                SnapInstanceToGround(block, groundY);
            }
        }
    }

    private bool IsNearEntrance(Vector3 position, List<Vector3> entrancePositions)
    {
        if (entrancePositions == null || entrancePositions.Count == 0)
        {
            return false;
        }

        float radius = Mathf.Max(0.1f, entranceOpeningWidth * 0.5f);
        float radiusSquared = radius * radius;
        foreach (Vector3 entrancePosition in entrancePositions)
        {
            Vector3 delta = position - entrancePosition;
            delta.y = 0f;
            if (delta.sqrMagnitude <= radiusSquared)
            {
                return true;
            }
        }
        return false;
    }

    private void CreateEntrancePrefabs(
        List<EntranceMarkerData> entrances,
        List<Vector3Json> boundaryPoints,
        float groundY,
        GameObject gatePrefab,
        GameObject roadBlockPrefab,
        Transform parent)
    {
        if (entrances == null)
        {
            return;
        }

        foreach (EntranceMarkerData entrance in entrances)
        {
            if (entrance.position == null)
            {
                continue;
            }

            Vector3 position = entrance.position.ToVector3();
            position.y = groundY;
            float yaw = FindNearestBoundaryYaw(position, boundaryPoints);

            if (createEntranceGatePanels && gatePrefab != null)
            {
                int panelCount = Mathf.Max(1, entranceGatePanelCount);
                float panelSpacing = panelCount > 1
                    ? Mathf.Max(0.1f, entranceOpeningWidth / panelCount)
                    : Mathf.Max(0.1f, entranceGatePanelSpacing);
                Vector3 tangent = Quaternion.Euler(0f, yaw, 0f) * Vector3.forward;
                float firstOffset = -0.5f * panelSpacing * (panelCount - 1);

                for (int panel = 0; panel < panelCount; panel++)
                {
                    Vector3 panelPosition = position + tangent * (firstOffset + panel * panelSpacing);
                    GameObject gate = Instantiate(gatePrefab, panelPosition, Quaternion.Euler(0f, yaw + 90f, 0f), parent);
                    gate.name = $"entrance_gate_{entrance.id}_{panel:00}";
                    SnapInstanceToGround(gate, groundY);
                }
            }

            if (createEntranceRoadBlocks && roadBlockPrefab != null)
            {
                Vector3 side = Quaternion.Euler(0f, yaw, 0f) * Vector3.right;
                Vector3 forward = Quaternion.Euler(0f, yaw, 0f) * Vector3.forward;
                float sideOffset = Mathf.Max(0.1f, Mathf.Max(entranceRoadBlockSideOffset, entranceOpeningWidth * 0.5f + 0.5f));
                float depthOffset = Mathf.Max(0.0f, entranceRoadBlockDepthOffset);
                Vector3[] offsets =
                {
                    side * sideOffset + forward * depthOffset,
                    -side * sideOffset + forward * depthOffset,
                    side * sideOffset - forward * depthOffset,
                    -side * sideOffset - forward * depthOffset
                };

                for (int i = 0; i < offsets.Length; i++)
                {
                    GameObject block = Instantiate(roadBlockPrefab, position + offsets[i], Quaternion.Euler(0f, yaw, 0f), parent);
                    block.name = $"entrance_roadblock_{entrance.id}_{i:00}";
                    SnapInstanceToGround(block, groundY);
                }
            }
        }
    }

    private float FindNearestBoundaryYaw(Vector3 position, List<Vector3Json> boundaryPoints)
    {
        if (boundaryPoints == null || boundaryPoints.Count < 2)
        {
            return 0f;
        }

        float bestDistance = float.MaxValue;
        float bestYaw = 0f;
        for (int i = 0; i < boundaryPoints.Count; i++)
        {
            Vector3 start = boundaryPoints[i].ToVector3();
            Vector3 end = boundaryPoints[(i + 1) % boundaryPoints.Count].ToVector3();
            Vector3 segment = end - start;
            segment.y = 0f;
            float segmentLengthSquared = segment.sqrMagnitude;
            if (segmentLengthSquared < 0.0001f)
            {
                continue;
            }

            float t = Vector3.Dot(position - start, segment) / segmentLengthSquared;
            t = Mathf.Clamp01(t);
            Vector3 closest = start + segment * t;
            float distance = (position - closest).sqrMagnitude;
            if (distance < bestDistance)
            {
                bestDistance = distance;
                bestYaw = Mathf.Atan2(segment.x, segment.z) * Mathf.Rad2Deg;
            }
        }

        return bestYaw;
    }

    private Material CreateColoredMaterial(Color color)
    {
        Shader shader = Shader.Find("HDRP/Lit");
        if (shader == null)
        {
            shader = Shader.Find("Standard");
        }
        if (shader == null)
        {
            shader = Shader.Find("Unlit/Color");
        }

        Material material = new Material(shader);
        material.color = color;
        if (material.HasProperty("_BaseColor"))
        {
            material.SetColor("_BaseColor", color);
        }
        if (material.HasProperty("_Color"))
        {
            material.SetColor("_Color", color);
        }
        if (color.a < 0.99f)
        {
            material.renderQueue = 3000;
            if (material.HasProperty("_SurfaceType"))
            {
                material.SetFloat("_SurfaceType", 1f);
            }
            if (material.HasProperty("_BlendMode"))
            {
                material.SetFloat("_BlendMode", 0f);
            }
            if (material.HasProperty("_AlphaCutoffEnable"))
            {
                material.SetFloat("_AlphaCutoffEnable", 0f);
            }
            if (material.HasProperty("_SrcBlend"))
            {
                material.SetFloat("_SrcBlend", (float)UnityEngine.Rendering.BlendMode.SrcAlpha);
            }
            if (material.HasProperty("_DstBlend"))
            {
                material.SetFloat("_DstBlend", (float)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
            }
            if (material.HasProperty("_ZWrite"))
            {
                material.SetFloat("_ZWrite", 0f);
            }
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.EnableKeyword("_ALPHABLEND_ON");
        }
        return material;
    }

    private string ResolveSceneJsonPath()
    {
        string requestedPath = Path.Combine(Application.streamingAssetsPath, streamingAssetsJson);
        if (File.Exists(requestedPath))
        {
            return requestedPath;
        }

        string[] fallbackNames =
        {
            "standard_layout_021_unity_scene.json",
            "standard_layout_021_scene.json"
        };

        foreach (string fallbackName in fallbackNames)
        {
            string fallbackPath = Path.Combine(Application.streamingAssetsPath, fallbackName);
            if (File.Exists(fallbackPath))
            {
                Debug.LogWarning($"Configured scene JSON '{streamingAssetsJson}' was not found. Using '{fallbackName}' instead.");
                streamingAssetsJson = fallbackName;
                return fallbackPath;
            }
        }

        return requestedPath;
    }

    private string DescribeStreamingAssets()
    {
        if (!Directory.Exists(Application.streamingAssetsPath))
        {
            return $"StreamingAssets folder does not exist: {Application.streamingAssetsPath}";
        }

        string[] jsonFiles = Directory.GetFiles(Application.streamingAssetsPath, "*.json");
        if (jsonFiles.Length == 0)
        {
            return $"No JSON files found in: {Application.streamingAssetsPath}";
        }

        return $"Available JSON files in {Application.streamingAssetsPath}: {string.Join(", ", Array.ConvertAll(jsonFiles, Path.GetFileName))}";
    }

    private GameObject InstantiateSceneObject(SceneObjectData obj, Transform parent)
    {
        if (obj.prefab.children != null && obj.prefab.children.Count > 0)
        {
            return InstantiateCompoundSceneObject(obj, parent);
        }

        GameObject prefab = LoadPrefab(obj.prefab.path);
        if (prefab == null)
        {
            Debug.LogWarning($"Prefab not found for {obj.id}: {obj.prefab.path}. Creating placeholder cube.");
            return CreatePlaceholder(obj, parent);
        }

        Vector3 position = obj.transform.position.ToVector3();
        Quaternion rotation = Quaternion.Euler(obj.transform.rotation.ToVector3());
        GameObject instance = Instantiate(prefab, position, rotation, parent);
        instance.name = $"{obj.id}_{obj.prefab.name}";

        if (scaleToLayoutFootprint)
        {
            ApplyLayoutScale(instance, obj);
        }

        return instance;
    }

    private GameObject InstantiateCompoundSceneObject(SceneObjectData obj, Transform parent)
    {
        GameObject root = new GameObject($"{obj.id}_{obj.prefab.name}");
        root.transform.SetParent(parent);
        root.transform.position = obj.transform.position.ToVector3();
        root.transform.rotation = Quaternion.Euler(obj.transform.rotation.ToVector3());

        int loadedChildren = 0;
        foreach (PrefabChildData child in obj.prefab.children)
        {
            GameObject childPrefab = LoadPrefab(child.path);
            if (childPrefab == null)
            {
                Debug.LogWarning($"Compound child prefab not found for {obj.id}: {child.path}");
                continue;
            }

            GameObject childInstance = Instantiate(childPrefab, root.transform);
            childInstance.name = string.IsNullOrEmpty(child.name) ? Path.GetFileNameWithoutExtension(child.path) : child.name;
            childInstance.transform.localPosition = child.position != null ? child.position.ToVector3() : Vector3.zero;
            childInstance.transform.localRotation = child.rotation != null ? Quaternion.Euler(child.rotation.ToVector3()) : Quaternion.identity;
            childInstance.transform.localScale = child.scale != null ? child.scale.ToVector3() : Vector3.one;
            loadedChildren++;
        }

        if (loadedChildren == 0)
        {
            Debug.LogWarning($"No compound children loaded for {obj.id}. Creating placeholder cube.");
            DestroyObject(root);
            return CreatePlaceholder(obj, parent);
        }

        return root;
    }

    private void CreateFootprintMarker(SceneObjectData obj, Transform parent)
    {
        if (obj.placement == null || obj.placement.bbox_size == null)
        {
            return;
        }

        Vector3 target = obj.placement.bbox_size.ToVector3();
        if (target.x <= 0.001f || target.z <= 0.001f)
        {
            return;
        }

        GameObject marker = GameObject.CreatePrimitive(PrimitiveType.Cube);
        marker.name = $"{obj.id}_layout_footprint";
        marker.transform.SetParent(parent);
        Vector3 position = obj.transform.position.ToVector3();
        marker.transform.position = new Vector3(position.x, 0.025f, position.z);
        marker.transform.rotation = Quaternion.Euler(0f, obj.transform.rotation.y, 0f);
        marker.transform.localScale = new Vector3(target.x, 0.05f, target.z);

        Collider collider = marker.GetComponent<Collider>();
        if (collider != null)
        {
            if (Application.isPlaying)
            {
                Destroy(collider);
            }
            else
            {
                DestroyImmediate(collider);
            }
        }

        Renderer renderer = marker.GetComponent<Renderer>();
        if (renderer != null)
        {
            Shader shader = Shader.Find("HDRP/Unlit");
            if (shader == null)
            {
                shader = Shader.Find("Unlit/Color");
            }
            if (shader != null)
            {
                Material material = new Material(shader);
                material.color = new Color(0.1f, 0.7f, 1.0f, 0.35f);
                renderer.sharedMaterial = material;
            }
        }
    }

    private GameObject CreatePlaceholder(SceneObjectData obj, Transform parent)
    {
        GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
        cube.name = $"{obj.id}_placeholder_{obj.prefab.name}";
        cube.transform.SetParent(parent);
        cube.transform.position = obj.transform.position.ToVector3();
        cube.transform.rotation = Quaternion.Euler(obj.transform.rotation.ToVector3());
        cube.transform.localScale = obj.placement.bbox_size.ToVector3();
        return cube;
    }

    private void ApplyLayoutScale(GameObject instance, SceneObjectData obj)
    {
        Vector3 target = obj.placement.bbox_size.ToVector3();
        Vector3 prefabSize = obj.placement.prefab_bbox_size != null
            ? obj.placement.prefab_bbox_size.ToVector3()
            : CalculateRendererBounds(instance).size;

        if (prefabSize.x <= 0.0001f || prefabSize.y <= 0.0001f || prefabSize.z <= 0.0001f)
        {
            return;
        }

        instance.transform.localScale = new Vector3(
            target.x / prefabSize.x,
            target.y / prefabSize.y,
            target.z / prefabSize.z
        );
    }

    private Bounds CalculateRendererBounds(GameObject instance)
    {
        Renderer[] renderers = instance.GetComponentsInChildren<Renderer>();
        if (renderers.Length == 0)
        {
            return new Bounds(instance.transform.position, Vector3.one);
        }

        Bounds bounds = renderers[0].bounds;
        for (int i = 1; i < renderers.Length; i++)
        {
            bounds.Encapsulate(renderers[i].bounds);
        }
        return bounds;
    }

    private void SnapInstanceToGround(GameObject instance, float groundY)
    {
        Renderer[] renderers = instance.GetComponentsInChildren<Renderer>();
        if (renderers.Length == 0)
        {
            return;
        }

        Bounds bounds = CalculateRendererBounds(instance);
        float deltaY = groundY - bounds.min.y;
        if (Mathf.Abs(deltaY) > 0.001f)
        {
            instance.transform.position += new Vector3(0f, deltaY, 0f);
        }
    }

    private void ClearExistingRoot()
    {
        GameObject existing = GameObject.Find(generatedRootName);
        if (existing != null)
        {
            DestroyObject(existing);
        }

        GameObject[] allObjects = FindObjectsByType<GameObject>(FindObjectsSortMode.None);
        foreach (GameObject obj in allObjects)
        {
            if (obj.name.StartsWith($"{generatedRootName}_", StringComparison.Ordinal))
            {
                DestroyObject(obj);
            }
        }
    }

    private void DestroyObject(GameObject obj)
    {
        if (Application.isPlaying)
        {
            Destroy(obj);
        }
        else
        {
            DestroyImmediate(obj);
        }
    }

    private GameObject LoadPrefab(string assetPath)
    {
#if UNITY_EDITOR
        if (!string.IsNullOrEmpty(assetPath))
        {
            return AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
        }
#endif
        return null;
    }
}
