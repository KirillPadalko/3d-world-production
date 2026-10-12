using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using UnityEngine;

namespace EnvGen.Importer.Editor
{
    [Serializable]
    public sealed class ImportSettings
    {
        public bool buildTerrain = true;
        public bool buildEntities = true;
        public bool applyAtmosphere = true;
        public bool buildAnnotations = true;

        [Tooltip("Stop when the manifest's contentHash does not match its content (edited after generation).")]
        public bool requireValidHash;

        [Tooltip("Upper limit for the Unity heightmap resolution (2^n + 1).")]
        public int maxTerrainResolution = 1025;

        [Tooltip("Project folder for generated assets (terrain data).")]
        public string assetFolder = "Assets/EnvGenImports";

        [Tooltip("Height of road, junction and water meshes above their points, against z-fighting.")]
        public float surfaceLift = 0.03f;

        [Tooltip("Points per span between two poles when drawing sagging cables.")]
        public int cableSamplesPerSpan = 8;

        [Tooltip("Add colliders to generated meshes and placeholder boxes.")]
        public bool addColliders = true;
    }

    /// <summary>Result of one import, also printed to the console.</summary>
    public sealed class ImportReport
    {
        public string ManifestPath { get; set; } = "";
        public string LocationId { get; set; } = "";
        public string ContentHash { get; set; } = "";
        public bool HashVerified { get; set; }
        public GameObject Root { get; set; }
        public int Created { get; set; }
        public int Updated { get; set; }
        public int Replaced { get; set; }
        public int Removed { get; set; }
        public int Placeholders { get; set; }
        public int GeneratedMeshes { get; set; }
        public bool TerrainBuilt { get; set; }

        /// <summary>Archetypes that fell back to a placeholder box (bind them in the registry).</summary>
        public SortedSet<string> UnboundArchetypes { get; } = new SortedSet<string>(StringComparer.Ordinal);
        public List<string> Warnings { get; } = new List<string>();

        public override string ToString()
        {
            var text = new StringBuilder();
            text.Append($"Environment Generator import of '{LocationId}' from {ManifestPath}: ");
            text.Append($"{Created} created, {Updated} updated, {Replaced} replaced, {Removed} removed, ");
            text.Append($"{GeneratedMeshes} generated meshes, {Placeholders} placeholders; ");
            text.Append(TerrainBuilt ? "terrain built; " : "no terrain; ");
            text.Append(HashVerified ? "content hash verified." : "CONTENT HASH NOT VERIFIED.");
            if (UnboundArchetypes.Count > 0)
            {
                text.Append("\nUnbound archetypes (placeholders): ").Append(string.Join(", ", UnboundArchetypes));
            }
            foreach (string warning in Warnings.Distinct())
            {
                text.Append("\nWarning: ").Append(warning);
            }
            return text.ToString();
        }
    }
}
