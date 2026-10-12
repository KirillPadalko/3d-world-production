using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using EnvGen.Importer.Core;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace EnvGen.Importer.Editor
{
    /// <summary>
    /// Imports a scene-manifest.json into the active scene. The manifest already uses
    /// Unity's axes (metres, +X east, +Y up, +Z north, Quaternion.Euler rotations), so
    /// positions, rotations and scales are used unchanged.
    ///
    /// Re-importing the same location updates the existing root: entities are matched
    /// by their stable ID, their "visual" child is rebuilt, removed entities are deleted
    /// and anything else you added is kept.
    /// </summary>
    public static class ManifestSceneImporter
    {
        public const string MenuRoot = "Tools/Environment Generator/";
        public const string EntitiesGroup = "Entities";
        public const string AnnotationsGroup = "Annotations";
        public const string TerrainName = "Terrain";
        public const string SunName = "Sun";

        /// <summary>Import <paramref name="manifestPath"/>; <paramref name="registry"/> may be null (all placeholders).</summary>
        public static ImportReport Import(string manifestPath, EnvGenPrefabRegistry registry, ImportSettings settings = null)
        {
            settings = settings ?? new ImportSettings();
            ManifestLoadResult load = ManifestReader.Load(manifestPath);
            SceneManifest manifest = load.Manifest;
            if (!load.HashMatches && settings.requireValidHash)
            {
                throw new InvalidOperationException(string.Join("\n", load.Warnings));
            }

            var report = new ImportReport
            {
                ManifestPath = manifestPath,
                LocationId = manifest.Source.LocationId,
                ContentHash = manifest.ContentHash,
                HashVerified = load.HashMatches,
            };
            report.Warnings.AddRange(load.Warnings);

            int undoGroup = Undo.GetCurrentGroup();
            Undo.SetCurrentGroupName($"Import {manifest.Source.LocationId}");
            try
            {
                GameObject root = FindOrCreateRoot(manifest.Source.LocationId);
                report.Root = root;
                UpdateRootInfo(root.GetComponent<EnvGenSceneRoot>(), load, manifestPath);

                Terrain terrain = null;
                if (settings.buildTerrain && manifest.Terrain != null)
                {
                    terrain = TerrainBuilder.Build(root.transform, manifest, registry, settings);
                    report.TerrainBuilt = terrain != null;
                }
                else
                {
                    terrain = root.GetComponentInChildren<Terrain>();
                }
                if (settings.buildEntities)
                {
                    EntityBuilder.Sync(root.transform, manifest, registry, settings, report);
                }
                if (settings.applyAtmosphere && manifest.Atmosphere != null)
                {
                    AtmosphereBuilder.Apply(root.transform, manifest.Atmosphere);
                }
                if (settings.buildAnnotations)
                {
                    AnnotationBuilder.Build(root.transform, manifest.Annotations, terrain);
                }
                EditorSceneManager.MarkSceneDirty(root.scene);
            }
            finally
            {
                EditorUtility.ClearProgressBar();
                Undo.CollapseUndoOperations(undoGroup);
            }

            if (report.HashVerified)
            {
                Debug.Log(report.ToString());
            }
            else
            {
                Debug.LogWarning(report.ToString());
            }
            return report;
        }

        /// <summary>The root of an earlier import of this location in any loaded scene, or a new one.</summary>
        public static GameObject FindOrCreateRoot(string locationId)
        {
            EnvGenSceneRoot existing = FindRoots().FirstOrDefault(r => r.locationId == locationId);
            if (existing != null)
            {
                return existing.gameObject;
            }
            var root = new GameObject($"EnvGen {locationId}");
            root.AddComponent<EnvGenSceneRoot>().locationId = locationId;
            Undo.RegisterCreatedObjectUndo(root, "Create location root");
            return root;
        }

        public static IEnumerable<EnvGenSceneRoot> FindRoots()
        {
            for (int i = 0; i < SceneManager.sceneCount; i++)
            {
                Scene scene = SceneManager.GetSceneAt(i);
                if (!scene.isLoaded)
                {
                    continue;
                }
                foreach (GameObject top in scene.GetRootGameObjects())
                {
                    foreach (EnvGenSceneRoot root in top.GetComponentsInChildren<EnvGenSceneRoot>(true))
                    {
                        yield return root;
                    }
                }
            }
        }

        /// <summary>Child of <paramref name="parent"/> with this name, created when missing.</summary>
        public static Transform Group(Transform parent, string name)
        {
            Transform child = parent.Find(name);
            if (child != null)
            {
                return child;
            }
            var group = new GameObject(name);
            Undo.RegisterCreatedObjectUndo(group, "Create group");
            group.transform.SetParent(parent, false);
            return group.transform;
        }

        public static Vector3 ToVector3(double[] values) =>
            new Vector3((float)values[0], (float)values[1], (float)values[2]);

        public static Vector3 ToVector3(Vec3 value) => new Vector3((float)value.X, (float)value.Y, (float)value.Z);

        public static Color ToColor(double[] rgb) =>
            new Color((float)rgb[0], (float)rgb[1], (float)rgb[2], 1f);

        public static string LocationAssetFolder(ImportSettings settings, string locationId)
        {
            string folder = settings.assetFolder.TrimEnd('/');
            EnsureFolder(folder);
            string location = folder + "/" + locationId;
            EnsureFolder(location);
            return location;
        }

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path))
            {
                return;
            }
            string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(parent) && !AssetDatabase.IsValidFolder(parent))
            {
                EnsureFolder(parent);
            }
            AssetDatabase.CreateFolder(parent, Path.GetFileName(path));
        }

        private static void UpdateRootInfo(EnvGenSceneRoot info, ManifestLoadResult load, string manifestPath)
        {
            Undo.RecordObject(info, "Update location info");
            SceneManifest manifest = load.Manifest;
            info.locationId = manifest.Source.LocationId;
            info.locationName = manifest.Source.LocationName;
            info.recipeId = manifest.Source.RecipeId;
            info.overridesId = manifest.Source.OverridesId ?? "";
            info.registryId = manifest.Source.RegistryId;
            info.seed = manifest.Source.Seed;
            info.generatorName = manifest.Generator.Name;
            info.generatorVersion = manifest.Generator.Version;
            info.manifestPath = manifestPath;
            info.contentHash = manifest.ContentHash;
            info.contentHashVerified = load.HashMatches;
            info.importedAtUtc = DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture);
        }
    }
}
