using System;
using System.IO;
using System.Linq;
using EnvGen.Importer.Core;
using UnityEditor;
using UnityEngine;

namespace EnvGen.Importer.Editor
{
    /// <summary>Tools > Environment Generator > Import Scene Manifest...</summary>
    public sealed class ImporterWindow : EditorWindow
    {
        private const string PathKey = "EnvGen.Importer.ManifestPath";
        private const string RegistryKey = "EnvGen.Importer.RegistryPath";

        [SerializeField] private string manifestPath = "";
        [SerializeField] private EnvGenPrefabRegistry registry;
        [SerializeField] private ImportSettings settings = new ImportSettings();
        private string status = "";
        private Vector2 scroll;

        [MenuItem(ManifestSceneImporter.MenuRoot + "Import Scene Manifest...")]
        public static void Open()
        {
            GetWindow<ImporterWindow>("EnvGen Import").Show();
        }

        private void OnEnable()
        {
            if (string.IsNullOrEmpty(manifestPath))
            {
                manifestPath = EditorPrefs.GetString(PathKey, "");
            }
            if (registry == null)
            {
                string registryPath = EditorPrefs.GetString(RegistryKey, "");
                if (!string.IsNullOrEmpty(registryPath))
                {
                    registry = AssetDatabase.LoadAssetAtPath<EnvGenPrefabRegistry>(registryPath);
                }
            }
        }

        private void OnGUI()
        {
            scroll = EditorGUILayout.BeginScrollView(scroll);
            EditorGUILayout.LabelField("Scene manifest", EditorStyles.boldLabel);
            using (new EditorGUILayout.HorizontalScope())
            {
                manifestPath = EditorGUILayout.TextField(manifestPath);
                if (GUILayout.Button("Browse", GUILayout.Width(70)))
                {
                    string directory = File.Exists(manifestPath) ? Path.GetDirectoryName(manifestPath) : "";
                    string chosen = EditorUtility.OpenFilePanel("Scene manifest", directory, "json");
                    if (!string.IsNullOrEmpty(chosen))
                    {
                        manifestPath = chosen;
                    }
                }
            }
            registry = (EnvGenPrefabRegistry)EditorGUILayout.ObjectField("Prefab registry", registry, typeof(EnvGenPrefabRegistry), false);
            if (registry == null)
            {
                EditorGUILayout.HelpBox("Without a registry every object becomes a placeholder box.", MessageType.Info);
            }

            EditorGUILayout.Space();
            EditorGUILayout.LabelField("Build", EditorStyles.boldLabel);
            settings.buildTerrain = EditorGUILayout.Toggle("Terrain", settings.buildTerrain);
            settings.buildEntities = EditorGUILayout.Toggle("Entities", settings.buildEntities);
            settings.applyAtmosphere = EditorGUILayout.Toggle("Lighting and fog", settings.applyAtmosphere);
            settings.buildAnnotations = EditorGUILayout.Toggle("Landmarks and gameplay", settings.buildAnnotations);
            settings.addColliders = EditorGUILayout.Toggle("Colliders", settings.addColliders);
            settings.requireValidHash = EditorGUILayout.Toggle("Require valid content hash", settings.requireValidHash);
            settings.maxTerrainResolution = EditorGUILayout.IntPopup(
                "Max terrain resolution", settings.maxTerrainResolution,
                new[] { "257", "513", "1025", "2049", "4097" }, new[] { 257, 513, 1025, 2049, 4097 });
            settings.assetFolder = EditorGUILayout.TextField("Asset folder", settings.assetFolder);

            EditorGUILayout.Space();
            using (new EditorGUI.DisabledScope(!File.Exists(manifestPath)))
            {
                using (new EditorGUILayout.HorizontalScope())
                {
                    if (GUILayout.Button("Check manifest"))
                    {
                        Check();
                    }
                    using (new EditorGUI.DisabledScope(registry == null))
                    {
                        if (GUILayout.Button("Add missing bindings to registry"))
                        {
                            AddBindings();
                        }
                    }
                }
                if (GUILayout.Button("Import into the active scene", GUILayout.Height(30)))
                {
                    Import();
                }
            }
            if (!string.IsNullOrEmpty(status))
            {
                EditorGUILayout.HelpBox(status, MessageType.None);
            }
            EditorGUILayout.EndScrollView();
        }

        private void Remember()
        {
            EditorPrefs.SetString(PathKey, manifestPath);
            EditorPrefs.SetString(RegistryKey, registry != null ? AssetDatabase.GetAssetPath(registry) : "");
        }

        private void Check()
        {
            Remember();
            try
            {
                ManifestLoadResult load = ManifestReader.Load(manifestPath);
                SceneManifest manifest = load.Manifest;
                int unbound = 0;
                if (registry != null)
                {
                    var byArchetype = registry.ArchetypeTable();
                    var byKind = registry.KindTable();
                    unbound = manifest.Entities
                        .Where(e => EntityShapes.Classify(e) == EntityShape.Object)
                        .Select(e => ArchetypeLookup.Choose(e, byArchetype, byKind))
                        .Count(c => c.Source == BindingSource.Placeholder);
                }
                status = $"{manifest.Source.LocationName} ({manifest.Source.LocationId}), generator {manifest.Generator.Version}\n"
                         + $"{manifest.Entities.Count} entities, terrain {(manifest.Terrain != null ? "yes" : "no")}, "
                         + $"{manifest.Annotations.Landmarks.Count} landmarks\n"
                         + (load.HashMatches ? "Content hash verified." : "Content hash MISMATCH: the file was edited after generation.")
                         + (registry != null ? $"\n{unbound} objects would be placeholders with this registry." : "");
            }
            catch (Exception exc)
            {
                status = exc.Message;
            }
        }

        private void AddBindings()
        {
            Remember();
            try
            {
                int added = RegistryTools.AddMissingBindings(registry, ManifestReader.Load(manifestPath).Manifest);
                status = $"Added {added} empty binding(s) to {registry.name}; assign prefabs and materials in the inspector.";
                Selection.activeObject = registry;
            }
            catch (Exception exc)
            {
                status = exc.Message;
            }
        }

        private void Import()
        {
            Remember();
            try
            {
                ImportReport report = ManifestSceneImporter.Import(manifestPath, registry, settings);
                status = report.ToString();
                if (report.Root != null)
                {
                    Selection.activeGameObject = report.Root;
                }
            }
            catch (Exception exc)
            {
                status = exc.Message;
                Debug.LogException(exc);
            }
        }
    }
}
