using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace EnvGen.Importer.Editor
{
    /// <summary>
    /// Entry points for automation.
    ///
    /// Command line (Unity closed):
    /// <code>
    /// Unity -batchmode -quit -projectPath &lt;project&gt;
    ///   -executeMethod EnvGen.Importer.Editor.BatchImport.Run
    ///   -envgenManifest out/dacha/scene-manifest.json
    ///   [-envgenRegistry Assets/EnvGenPrefabRegistry.asset]
    ///   [-envgenScene Assets/Scenes/Dacha.unity]
    ///   [-envgenRequireValidHash]
    /// </code>
    ///
    /// From an editor script or a Unity MCP "execute code" tool:
    /// <c>EnvGen.Importer.Editor.BatchImport.ImportIntoScene(manifest, registry, scene)</c>.
    /// </summary>
    public static class BatchImport
    {
        public static void Run()
        {
            string[] args = Environment.GetCommandLineArgs();
            try
            {
                string manifest = Argument(args, "-envgenManifest")
                                  ?? throw new ArgumentException("-envgenManifest <path> is required");
                string report = ImportIntoScene(
                    manifest,
                    Argument(args, "-envgenRegistry"),
                    Argument(args, "-envgenScene"),
                    Array.IndexOf(args, "-envgenRequireValidHash") >= 0);
                Debug.Log(report);
            }
            catch (Exception exc)
            {
                Debug.LogException(exc);
                if (Application.isBatchMode)
                {
                    EditorApplication.Exit(1);
                }
            }
        }

        /// <summary>
        /// Import a manifest. With <paramref name="scenePath"/> the scene is opened (or
        /// created) first and saved afterwards; otherwise the active scene is used and
        /// left unsaved. Returns the import summary.
        /// </summary>
        public static string ImportIntoScene(string manifestPath, string registryPath = null, string scenePath = null, bool requireValidHash = false)
        {
            if (!File.Exists(manifestPath))
            {
                throw new FileNotFoundException("Scene manifest not found", manifestPath);
            }
            EnvGenPrefabRegistry registry = null;
            if (!string.IsNullOrEmpty(registryPath))
            {
                registry = AssetDatabase.LoadAssetAtPath<EnvGenPrefabRegistry>(registryPath)
                           ?? throw new ArgumentException($"No EnvGenPrefabRegistry at '{registryPath}'");
            }
            Scene scene = SceneManager.GetActiveScene();
            if (!string.IsNullOrEmpty(scenePath))
            {
                scene = File.Exists(scenePath)
                    ? EditorSceneManager.OpenScene(scenePath, OpenSceneMode.Single)
                    : EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            }
            var settings = new ImportSettings { requireValidHash = requireValidHash };
            ImportReport report = ManifestSceneImporter.Import(manifestPath, registry, settings);
            if (!string.IsNullOrEmpty(scenePath))
            {
                string directory = Path.GetDirectoryName(scenePath);
                if (!string.IsNullOrEmpty(directory))
                {
                    Directory.CreateDirectory(directory);
                }
                EditorSceneManager.SaveScene(scene, scenePath);
                AssetDatabase.Refresh();
            }
            return report.ToString();
        }

        private static string Argument(string[] args, string name)
        {
            int index = Array.IndexOf(args, name);
            return index >= 0 && index + 1 < args.Length ? args[index + 1] : null;
        }
    }
}
