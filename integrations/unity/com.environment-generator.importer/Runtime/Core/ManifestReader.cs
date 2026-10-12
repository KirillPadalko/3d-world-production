// Loads scene-manifest.json, refuses unsupported versions and any coordinate
// convention other than the location frame (axes are never reinterpreted),
// checks basic structure and recomputes the content hash.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace EnvGen.Importer.Core
{
    public sealed class ManifestFormatException : Exception
    {
        public ManifestFormatException(string message, IReadOnlyList<string> problems)
            : base(message + (problems.Count > 0 ? ":\n - " + string.Join("\n - ", problems) : ""))
        {
            Problems = problems;
        }

        public IReadOnlyList<string> Problems { get; }
    }

    public sealed class ManifestLoadResult
    {
        public SceneManifest Manifest { get; set; }
        public JObject Raw { get; set; }

        /// <summary>Hash recomputed from the file content.</summary>
        public string ComputedHash { get; set; } = "";

        /// <summary>True when the file is exactly what the generator wrote.</summary>
        public bool HashMatches { get; set; }
        public List<string> Warnings { get; } = new List<string>();
    }

    public static class ManifestReader
    {
        public const string SupportedVersion = "1.0";

        /// <summary>The only spatial convention this importer accepts (LocationBlueprint v1.0).</summary>
        public static readonly IReadOnlyList<KeyValuePair<string, string>> ExpectedFrame = new[]
        {
            new KeyValuePair<string, string>("unit", "meter"),
            new KeyValuePair<string, string>("upAxis", "+y"),
            new KeyValuePair<string, string>("eastAxis", "+x"),
            new KeyValuePair<string, string>("northAxis", "+z"),
            new KeyValuePair<string, string>("handedness", "left"),
            new KeyValuePair<string, string>("yawConvention", "degrees_clockwise_from_north"),
            new KeyValuePair<string, string>("rotationOrder", "zxy"),
            new KeyValuePair<string, string>("forwardAxis", "+z"),
            new KeyValuePair<string, string>("origin", "southwest_corner"),
        };

        public static ManifestLoadResult Load(string path)
        {
            return Parse(File.ReadAllText(path, Encoding.UTF8));
        }

        public static ManifestLoadResult Parse(string json)
        {
            JObject raw;
            try
            {
                using (var reader = new JsonTextReader(new StringReader(json)))
                {
                    reader.DateParseHandling = DateParseHandling.None;
                    reader.FloatParseHandling = FloatParseHandling.Double;
                    raw = JObject.Load(reader);
                }
            }
            catch (JsonReaderException exc)
            {
                throw new ManifestFormatException("The manifest is not a JSON object", new[] { exc.Message });
            }

            var problems = new List<string>();
            string version = raw.Value<string>("manifestVersion");
            if (version != SupportedVersion)
            {
                problems.Add($"manifestVersion '{version ?? "(missing)"}' is not supported (expected {SupportedVersion})");
            }
            var frame = raw["coordinateSystem"] as JObject;
            if (frame == null)
            {
                problems.Add("coordinateSystem is missing");
            }
            else
            {
                foreach (KeyValuePair<string, string> expected in ExpectedFrame)
                {
                    string actual = frame.Value<string>(expected.Key);
                    if (actual != expected.Value)
                    {
                        problems.Add($"coordinateSystem.{expected.Key} is '{actual ?? "(missing)"}', expected '{expected.Value}'");
                    }
                }
            }
            if (problems.Count > 0)
            {
                throw new ManifestFormatException("Unsupported scene manifest", problems);
            }

            SceneManifest manifest;
            try
            {
                var serializer = JsonSerializer.Create(new JsonSerializerSettings
                {
                    MissingMemberHandling = MissingMemberHandling.Ignore,
                    DateParseHandling = DateParseHandling.None,
                    FloatParseHandling = FloatParseHandling.Double,
                });
                manifest = raw.ToObject<SceneManifest>(serializer);
            }
            catch (JsonException exc)
            {
                throw new ManifestFormatException("The manifest does not match the v1.0 contract", new[] { exc.Message });
            }

            CheckStructure(manifest, problems);
            if (problems.Count > 0)
            {
                throw new ManifestFormatException("The manifest is inconsistent", problems);
            }

            var result = new ManifestLoadResult { Manifest = manifest, Raw = raw };
            result.ComputedHash = ContentHash.Compute(raw);
            result.HashMatches = string.Equals(result.ComputedHash, manifest.ContentHash, StringComparison.Ordinal);
            if (!result.HashMatches)
            {
                result.Warnings.Add(
                    $"contentHash mismatch: the file says {manifest.ContentHash}, its content hashes to "
                    + $"{result.ComputedHash}. The manifest was edited after generation.");
            }
            if (manifest.Statistics != null && manifest.Statistics.EntityCount != manifest.Entities.Count)
            {
                result.Warnings.Add(
                    $"statistics.entityCount is {manifest.Statistics.EntityCount} but the file has "
                    + $"{manifest.Entities.Count} entities.");
            }
            return result;
        }

        private static void CheckStructure(SceneManifest manifest, List<string> problems)
        {
            if (manifest.Entities == null)
            {
                problems.Add("entities is missing");
                return;
            }
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (ManifestEntity entity in manifest.Entities)
            {
                if (string.IsNullOrEmpty(entity.Id))
                {
                    problems.Add("an entity has no id");
                    continue;
                }
                if (!seen.Add(entity.Id))
                {
                    problems.Add($"duplicate entity id '{entity.Id}'");
                }
                EntityTransform t = entity.Transform;
                if (t == null || !IsVector(t.Position, 3) || !IsVector(t.RotationDeg, 3) || !IsVector(t.Scale, 3))
                {
                    problems.Add($"entity '{entity.Id}' has an invalid transform");
                }
                EntityGeometry g = entity.Geometry;
                if (g != null)
                {
                    int minimum = g.Type == "polygon" ? 3 : 2;
                    if ((g.Type != "polyline" && g.Type != "polygon") || g.Points == null
                        || g.Points.Length < minimum || g.Points.Any(p => !IsVector(p, 3)))
                    {
                        problems.Add($"entity '{entity.Id}' has invalid geometry");
                    }
                }
            }
            TerrainGrid terrain = manifest.Terrain;
            if (terrain != null)
            {
                if (terrain.Columns < 2 || terrain.Rows < 2 || terrain.CellSizeM <= 0
                    || terrain.Heights == null || terrain.Heights.Length != terrain.Rows
                    || terrain.Heights.Any(row => row == null || row.Length != terrain.Columns)
                    || !IsVector(terrain.Origin, 2))
                {
                    problems.Add("terrain heights do not match columns x rows");
                }
            }
        }

        private static bool IsVector(double[] values, int length)
        {
            return values != null && values.Length == length && values.All(v => !double.IsNaN(v) && !double.IsInfinity(v));
        }
    }
}
