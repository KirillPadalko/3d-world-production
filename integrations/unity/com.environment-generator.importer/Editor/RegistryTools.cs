using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using EnvGen.Importer.Core;
using UnityEditor;
using UnityEngine;

namespace EnvGen.Importer.Editor
{
    public static class RegistryTools
    {
        [MenuItem(ManifestSceneImporter.MenuRoot + "Create Prefab Registry")]
        public static void CreateRegistryMenu()
        {
            string folder = "Assets";
            if (Selection.activeObject != null)
            {
                string selected = AssetDatabase.GetAssetPath(Selection.activeObject);
                if (!string.IsNullOrEmpty(selected))
                {
                    folder = AssetDatabase.IsValidFolder(selected) ? selected : Path.GetDirectoryName(selected)?.Replace('\\', '/') ?? "Assets";
                }
            }
            EnvGenPrefabRegistry registry = CreateRegistry(AssetDatabase.GenerateUniqueAssetPath(folder + "/EnvGenPrefabRegistry.asset"));
            Selection.activeObject = registry;
        }

        public static EnvGenPrefabRegistry CreateRegistry(string assetPath)
        {
            var registry = ScriptableObject.CreateInstance<EnvGenPrefabRegistry>();
            AssetDatabase.CreateAsset(registry, assetPath);
            AssetDatabase.SaveAssets();
            return registry;
        }

        /// <summary>
        /// Add an empty binding for every archetype, generated-mesh kind and ground cover the
        /// manifest uses and the registry does not list yet, so you only drag prefabs and
        /// materials in. Returns the number of entries added.
        /// </summary>
        public static int AddMissingBindings(EnvGenPrefabRegistry registry, SceneManifest manifest)
        {
            Undo.RecordObject(registry, "Add registry bindings");
            int added = 0;
            var archetypes = new HashSet<string>(registry.archetypes.Select(b => b.archetypeId), StringComparer.Ordinal);
            var materials = new HashSet<string>(registry.materials.Select(b => b.key), StringComparer.Ordinal);
            foreach (ManifestEntity entity in manifest.Entities.OrderBy(e => e.ArchetypeId, StringComparer.Ordinal))
            {
                EntityShape shape = EntityShapes.Classify(entity);
                if (shape == EntityShape.Object)
                {
                    if (archetypes.Add(entity.ArchetypeId))
                    {
                        registry.archetypes.Add(new EnvGenPrefabRegistry.ArchetypeBinding
                        {
                            archetypeId = entity.ArchetypeId,
                            fit = entity.Category == "vegetation" || entity.Category == "prop"
                                ? FitMode.FitHeightUniform
                                : FitMode.FitDimensions,
                        });
                        added++;
                    }
                }
                else if (shape == EntityShape.RoadRibbon || shape == EntityShape.RoadJunction || shape == EntityShape.WaterSurface)
                {
                    string key = ArchetypeLookup.KindKey(entity.Category, entity.Kind);
                    if (materials.Add(key))
                    {
                        registry.materials.Add(new EnvGenPrefabRegistry.MaterialBinding { key = key });
                        added++;
                    }
                }
            }
            string cover = manifest.Terrain?.GroundCover;
            if (!string.IsNullOrEmpty(cover) && registry.terrainLayers.All(b => b.groundCover != cover))
            {
                registry.terrainLayers.Add(new EnvGenPrefabRegistry.TerrainLayerBinding { groundCover = cover });
                added++;
            }
            EditorUtility.SetDirty(registry);
            AssetDatabase.SaveAssets();
            return added;
        }
    }
}
