using System.Linq;
using EnvGen.Importer.Core;
using UnityEditor;
using UnityEngine;

namespace EnvGen.Importer.Editor
{
    /// <summary>Unity Terrain from the manifest heightfield (saved as a TerrainData asset).</summary>
    internal static class TerrainBuilder
    {
        public static Terrain Build(Transform root, SceneManifest manifest, EnvGenPrefabRegistry registry, ImportSettings settings)
        {
            TerrainGrid grid = manifest.Terrain;
            int resolution = HeightfieldResampler.ChooseResolution(grid.Columns, grid.Rows, settings.maxTerrainResolution);
            HeightfieldSamples samples = HeightfieldResampler.Resample(grid, resolution);

            string folder = ManifestSceneImporter.LocationAssetFolder(settings, manifest.Source.LocationId);
            string path = $"{folder}/{manifest.Source.LocationId}.terrain.asset";
            TerrainData data = AssetDatabase.LoadAssetAtPath<TerrainData>(path);
            if (data == null)
            {
                data = new TerrainData();
                AssetDatabase.CreateAsset(data, path);
            }
            else
            {
                Undo.RecordObject(data, "Update terrain");
            }
            // Resolution first: changing it resets the heights.
            data.heightmapResolution = samples.Resolution;
            data.size = new Vector3((float)samples.SizeX, (float)samples.HeightRange, (float)samples.SizeZ);
            data.SetHeights(0, 0, samples.Normalized);

            string terrainArchetype = manifest.Entities.FirstOrDefault(e => e.Category == "terrain")?.ArchetypeId;
            TerrainLayer layer = registry != null ? registry.LayerFor(grid.GroundCover, terrainArchetype) : null;
            if (layer != null)
            {
                data.terrainLayers = new[] { layer };
            }
            EditorUtility.SetDirty(data);
            AssetDatabase.SaveAssets();

            Transform existing = root.Find(ManifestSceneImporter.TerrainName);
            Terrain terrain = existing != null ? existing.GetComponent<Terrain>() : null;
            if (terrain == null)
            {
                GameObject created = Terrain.CreateTerrainGameObject(data);
                created.name = ManifestSceneImporter.TerrainName;
                Undo.RegisterCreatedObjectUndo(created, "Create terrain");
                created.transform.SetParent(root, false);
                terrain = created.GetComponent<Terrain>();
            }
            else
            {
                Undo.RecordObject(terrain, "Update terrain");
                terrain.terrainData = data;
                TerrainCollider collider = terrain.GetComponent<TerrainCollider>();
                if (collider != null)
                {
                    Undo.RecordObject(collider, "Update terrain collider");
                    collider.terrainData = data;
                }
            }
            Undo.RecordObject(terrain.transform, "Place terrain");
            // Sample (0, 0) of the manifest grid is the south-west corner; Unity terrains cannot rotate.
            terrain.transform.localPosition = new Vector3((float)grid.Origin[0], (float)samples.MinElevation, (float)grid.Origin[1]);
            terrain.transform.localRotation = Quaternion.identity;
            return terrain;
        }
    }
}
