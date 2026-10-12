// Tests of the engine-free importer core. Run with:
//   dotnet test integrations/unity/tests/EnvGen.Importer.Core.Tests

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using EnvGen.Importer.Core;
using Newtonsoft.Json.Linq;
using Xunit;

namespace EnvGen.Importer.Core.Tests
{
    internal static class Repo
    {
        public static string Root
        {
            get
            {
                string dir = AppContext.BaseDirectory;
                while (dir != null && !File.Exists(Path.Combine(dir, "pyproject.toml")))
                {
                    dir = Path.GetDirectoryName(dir);
                }
                return dir ?? throw new InvalidOperationException("repository root not found");
            }
        }

        public static IEnumerable<string> ExpectedManifests =>
            Directory.GetDirectories(Path.Combine(Root, "examples", "expected-output"))
                .Select(d => Path.Combine(d, "scene-manifest.json"))
                .OrderBy(p => p, StringComparer.Ordinal);

        public static string Dacha =>
            Path.Combine(Root, "examples", "expected-output", "dacha-forest-edge.dacha-overgrown.designer-pass-01", "scene-manifest.json");
    }

    public class ContentHashTests
    {
        public static IEnumerable<object[]> Manifests => Repo.ExpectedManifests.Select(p => new object[] { Path.GetFileName(Path.GetDirectoryName(p)) });

        [Theory]
        [MemberData(nameof(Manifests))]
        public void HashOfEveryGeneratedManifestMatchesPython(string caseName)
        {
            string path = Path.Combine(Repo.Root, "examples", "expected-output", caseName, "scene-manifest.json");
            ManifestLoadResult result = ManifestReader.Load(path);
            Assert.True(result.HashMatches, result.Warnings.FirstOrDefault());
            Assert.Equal(result.Manifest.ContentHash, result.ComputedHash);
            Assert.Empty(result.Warnings);
        }

        [Fact]
        public void EditedManifestIsDetected()
        {
            JObject raw = JObject.Parse(File.ReadAllText(Repo.Dacha));
            raw["entities"][0]["transform"]["position"][0] = 999.5;
            ManifestLoadResult result = ManifestReader.Parse(raw.ToString());
            Assert.False(result.HashMatches);
            Assert.Contains(result.Warnings, w => w.Contains("contentHash mismatch"));
        }

        [Fact]
        public void PythonRoundAndReprMatchReferenceValues()
        {
            string path = Path.Combine(AppContext.BaseDirectory, "python-float-vectors.json");
            JArray vectors = JArray.Parse(File.ReadAllText(path));
            Assert.True(vectors.Count > 40);
            foreach (JToken pair in vectors)
            {
                string input = (string)pair[0];
                string expectedRounded = (string)pair[1];
                double value = double.Parse(input, System.Globalization.CultureInfo.InvariantCulture);
                Assert.Equal(input, PythonFloat.Repr(value));
                double rounded = PythonFloat.Round(value, 4);
                Assert.Equal(expectedRounded, PythonFloat.Repr(rounded == 0.0 ? 0.0 : rounded));
            }
        }

        [Fact]
        public void CanonicalJsonSortsKeysAndEscapesLikePython()
        {
            var token = JObject.Parse("{\"b\": 1, \"a\": [1.0, 2.5, true, null], \"c\": \"x\\n\\u0001\\u00e9\\\"\"}");
            Assert.Equal("{\"a\":[1.0,2.5,true,null],\"b\":1,\"c\":\"x\\n\\u0001é\\\"\"}", CanonicalJson.Serialize(token));
        }
    }

    public class ManifestReaderTests
    {
        [Fact]
        public void LoadsTheDachaManifest()
        {
            ManifestLoadResult result = ManifestReader.Load(Repo.Dacha);
            SceneManifest manifest = result.Manifest;
            Assert.Equal("dacha-forest-edge", manifest.Source.LocationId);
            Assert.Equal(manifest.Statistics.EntityCount, manifest.Entities.Count);
            Assert.NotNull(manifest.Terrain);
            Assert.Equal(manifest.Terrain.Rows, manifest.Terrain.Heights.Length);
            ManifestEntity house = manifest.Entities.Single(e => e.Id == "building.b-house-02");
            Assert.Equal(180.0, house.Transform.RotationDeg[1]);
            Assert.Equal("wood_board", house.Parameters["wallMaterial"].Value<string>());
            Assert.Contains("dacha-designer-pass-01#entityOperations[0]", house.Provenance.Overrides);
            Assert.Equal(4, manifest.Annotations.Landmarks.Count);
            Assert.Equal("block", manifest.Annotations.Gameplay.CoverZones.Single(z => z.Id == "cz-fence-04").Movement);
        }

        [Theory]
        [InlineData("upAxis", "+z")]
        [InlineData("handedness", "right")]
        [InlineData("yawConvention", "degrees_counterclockwise")]
        public void RefusesOtherCoordinateConventions(string field, string value)
        {
            JObject raw = JObject.Parse(File.ReadAllText(Repo.Dacha));
            raw["coordinateSystem"][field] = value;
            var error = Assert.Throws<ManifestFormatException>(() => ManifestReader.Parse(raw.ToString()));
            Assert.Contains(error.Problems, p => p.Contains("coordinateSystem." + field));
        }

        [Fact]
        public void RefusesUnknownVersionsAndBrokenStructure()
        {
            JObject raw = JObject.Parse(File.ReadAllText(Repo.Dacha));
            raw["manifestVersion"] = "2.0";
            Assert.Throws<ManifestFormatException>(() => ManifestReader.Parse(raw.ToString()));

            raw = JObject.Parse(File.ReadAllText(Repo.Dacha));
            var entities = (JArray)raw["entities"];
            entities.Add(entities[0].DeepClone());
            var duplicate = Assert.Throws<ManifestFormatException>(() => ManifestReader.Parse(raw.ToString()));
            Assert.Contains(duplicate.Problems, p => p.StartsWith("duplicate entity id"));

            Assert.Throws<ManifestFormatException>(() => ManifestReader.Parse("[1, 2]"));
        }
    }

    public class GeometryTests
    {
        private static void AssertFacesUp(MeshData mesh)
        {
            for (int t = 0; t < mesh.Triangles.Count; t += 3)
            {
                Vec3 a = mesh.Vertices[mesh.Triangles[t]];
                Vec3 b = mesh.Vertices[mesh.Triangles[t + 1]];
                Vec3 c = mesh.Vertices[mesh.Triangles[t + 2]];
                Assert.True(Vec3.Cross(b - a, c - a).Y > 0, $"triangle {t / 3} faces down");
            }
        }

        private static double Area(MeshData mesh)
        {
            double area = 0;
            for (int t = 0; t < mesh.Triangles.Count; t += 3)
            {
                Vec3 a = mesh.Vertices[mesh.Triangles[t]];
                Vec3 b = mesh.Vertices[mesh.Triangles[t + 1]];
                Vec3 c = mesh.Vertices[mesh.Triangles[t + 2]];
                area += Vec3.Cross(b - a, c - a).Y / 2.0;
            }
            return area;
        }

        [Fact]
        public void ResolutionIsPowerOfTwoPlusOne()
        {
            Assert.Equal(33, HeightfieldResampler.ChooseResolution(10, 10));
            Assert.Equal(129, HeightfieldResampler.ChooseResolution(81, 61));
            Assert.Equal(513, HeightfieldResampler.ChooseResolution(300, 20, 513));
            Assert.Equal(1025, HeightfieldResampler.ChooseResolution(5000, 5000));
        }

        [Fact]
        public void ResampleKeepsCornersAndRange()
        {
            var grid = new TerrainGrid
            {
                CellSizeM = 2.0,
                Columns = 3,
                Rows = 2,
                Heights = new[] { new[] { 10.0, 11.0, 12.0 }, new[] { 14.0, 15.0, 16.0 } },
                MinElevationM = 10.0,
                MaxElevationM = 16.0,
            };
            HeightfieldSamples samples = HeightfieldResampler.Resample(grid, 33);
            Assert.Equal(4.0, samples.SizeX);
            Assert.Equal(2.0, samples.SizeZ);
            Assert.Equal(6.0, samples.HeightRange);
            Assert.Equal(0f, samples.Normalized[0, 0]);          // south-west
            Assert.Equal(1f, samples.Normalized[32, 32]);        // north-east
            Assert.Equal((float)(12.0 - 10.0) / 6f, samples.Normalized[0, 32], 5);  // south-east
            Assert.Equal((float)(13.0 - 10.0) / 6f, samples.Normalized[16, 16], 5); // centre (bilinear)
        }

        [Fact]
        public void DachaTerrainResamplesWithinRange()
        {
            TerrainGrid grid = ManifestReader.Load(Repo.Dacha).Manifest.Terrain;
            HeightfieldSamples samples = HeightfieldResampler.Resample(grid, HeightfieldResampler.ChooseResolution(grid.Columns, grid.Rows));
            float[] all = samples.Normalized.Cast<float>().ToArray();
            Assert.Equal(0f, all.Min(), 3);
            Assert.Equal(1f, all.Max(), 3);
            Assert.Equal(160.0, samples.SizeX);
            Assert.Equal(120.0, samples.SizeZ);
        }

        [Fact]
        public void RoadRibbonHasTheRoadWidthAndFacesUp()
        {
            var points = new List<Vec3> { new Vec3(0, 0, 0), new Vec3(0, 0, 10), new Vec3(10, 1, 10), new Vec3(10, 1, 10) };
            MeshData mesh = RibbonMeshBuilder.Build(points, 4.0, 0.05);
            Assert.Equal(6, mesh.Vertices.Count); // duplicate point dropped
            Assert.Equal(12, mesh.Triangles.Count);
            AssertFacesUp(mesh);
            // Heading north, the left edge is west (x = -2) and the right edge east (x = +2).
            Assert.Equal(-2.0, mesh.Vertices[0].X, 9);
            Assert.Equal(2.0, mesh.Vertices[1].X, 9);
            Assert.Equal(0.05, mesh.Vertices[0].Y, 9);
            Assert.Equal(new[] { 1.0, 0.0 }, mesh.Uvs[1]);
        }

        [Fact]
        public void PolygonsTriangulateInEitherOrientation()
        {
            var lShape = new List<double[]>
            {
                new[] { 0.0, 0.0 }, new[] { 4.0, 0.0 }, new[] { 4.0, 1.0 },
                new[] { 1.0, 1.0 }, new[] { 1.0, 3.0 }, new[] { 0.0, 3.0 },
            };
            foreach (List<double[]> ring in new[] { lShape, Enumerable.Reverse(lShape).ToList() })
            {
                List<int> triangles = PolygonTriangulator.Triangulate(ring);
                Assert.Equal(3 * (ring.Count - 2), triangles.Count);
                var mesh = new MeshData();
                mesh.Vertices.AddRange(ring.Select(p => new Vec3(p[0], 0, p[1])));
                mesh.Triangles.AddRange(triangles);
                AssertFacesUp(mesh);
                Assert.Equal(6.0, Area(mesh), 9);
            }
        }

        [Fact]
        public void WaterAndJunctionSurfacesFaceUp()
        {
            ManifestEntity pond = ManifestReader.Load(Repo.Dacha).Manifest.Entities.Single(e => e.Id == "water.wb-pond");
            MeshData water = SurfaceMeshBuilder.Polygon(pond.Geometry.Points, 0.0);
            AssertFacesUp(water);
            Assert.True(Area(water) > 50);

            MeshData disc = SurfaceMeshBuilder.Disc(new Vec3(5, 2, 5), 3.0, 24, 0.04);
            AssertFacesUp(disc);
            Assert.Equal(Math.PI * 9.0, Area(disc), 0); // polygon area approaches the circle
            Assert.Equal(2.04, disc.Vertices[0].Y, 9);
        }

        [Fact]
        public void CablesSagBetweenSupports()
        {
            var supports = new List<Vec3> { new Vec3(0, 8, 0), new Vec3(30, 8, 0), new Vec3(60, 9, 0) };
            List<Vec3> points = CableSag.Sample(supports, 0.6, 4);
            Assert.Equal(9, points.Count);
            Assert.Equal(supports[1], points[4]);
            Assert.Equal(supports[2], points[8]);
            Assert.Equal(8.0 - 0.6, points[2].Y, 9); // middle of the first span
        }

        [Fact]
        public void ShapesFollowTheManifest()
        {
            List<ManifestEntity> entities = ManifestReader.Load(Repo.Dacha).Manifest.Entities;
            EntityShape ShapeOf(string id) => EntityShapes.Classify(entities.Single(e => e.Id == id));
            Assert.Equal(EntityShape.RoadRibbon, ShapeOf("road.s-main-west"));
            Assert.Equal(EntityShape.Cable, ShapeOf("infrastructure.w-main"));
            Assert.Equal(EntityShape.WaterSurface, ShapeOf("water.wb-pond"));
            Assert.Equal(EntityShape.Terrain, ShapeOf("terrain"));
            Assert.Equal(EntityShape.Object, ShapeOf("building.b-house-02"));
            Assert.Contains(entities, e => EntityShapes.Classify(e) == EntityShape.RoadJunction);
        }
    }

    public class PlanningTests
    {
        private static ManifestEntity Entity(string id, string archetype, int variant = 0, string kind = "house") =>
            new ManifestEntity { Id = id, Category = "building", Kind = kind, ArchetypeId = archetype, Variant = variant };

        [Fact]
        public void ArchetypeBeatsKindBeatsPlaceholder()
        {
            var byArchetype = new Dictionary<string, IReadOnlyList<string>>
            {
                ["building.dacha.wooden_house_small"] = new[] { "small-a", "small-b" },
                ["building.empty"] = new string[] { null },
            };
            var byKind = new Dictionary<string, IReadOnlyList<string>> { ["building/house"] = new[] { "generic-house" } };

            BindingChoice<string> exact = ArchetypeLookup.Choose(Entity("a", "building.dacha.wooden_house_small", 3), byArchetype, byKind);
            Assert.Equal((BindingSource.Archetype, "small-b", 1), (exact.Source, exact.Asset, exact.VariantIndex));

            BindingChoice<string> byKindChoice = ArchetypeLookup.Choose(Entity("b", "building.empty"), byArchetype, byKind);
            Assert.Equal((BindingSource.Kind, "generic-house"), (byKindChoice.Source, byKindChoice.Asset));

            BindingChoice<string> none = ArchetypeLookup.Choose(Entity("c", "building.unknown", kind: "barn"), byArchetype, byKind);
            Assert.Equal(BindingSource.Placeholder, none.Source);
            Assert.Null(none.Asset);
        }

        [Fact]
        public void ReimportMatchesByStableId()
        {
            var existing = new[]
            {
                new ExistingEntityState { Id = "b", Category = "building", Kind = "house", ArchetypeId = "x", Variant = 0 },
                new ExistingEntityState { Id = "a", Category = "building", Kind = "house", ArchetypeId = "x", Variant = 0 },
                new ExistingEntityState { Id = "gone", Category = "building", Kind = "house", ArchetypeId = "x", Variant = 0 },
            };
            var incoming = new[] { Entity("b", "x"), Entity("a", "y"), Entity("new", "x") };
            ReimportPlan plan = ReimportPlanner.Plan(existing, incoming);
            Assert.Equal(new[] { "new" }, plan.Create);
            Assert.Equal(new[] { "b" }, plan.Update);
            Assert.Equal(new[] { "a" }, plan.Replace);
            Assert.Equal(new[] { "gone" }, plan.Remove);
        }

        [Fact]
        public void AssetsAreFittedToEntityDimensions()
        {
            var dims = new Dimensions { WidthM = 6, HeightM = 5, DepthM = 4 };
            // A 3 x 2.5 x 2 model whose pivot is at its centre.
            var center = new Vec3(0, 0, 0);
            var size = new Vec3(3, 2.5, 2);

            FitResult fit = AssetFitting.Fit(FitMode.FitDimensions, center, size, dims, new[] { 1.0, 1.0, 1.0 });
            Assert.Equal((2.0, 2.0, 2.0), (fit.Scale.X, fit.Scale.Y, fit.Scale.Z));
            Assert.Equal(2.5, fit.Offset.Y, 9); // bottom of the scaled bounds lands on the pivot

            FitResult uniform = AssetFitting.Fit(FitMode.FitHeightUniform, center, size, dims, new[] { 1.0, 1.0, 1.0 });
            Assert.Equal((2.0, 2.0, 2.0), (uniform.Scale.X, uniform.Scale.Y, uniform.Scale.Z));

            FitResult manifest = AssetFitting.Fit(FitMode.ManifestScale, center, size, dims, new[] { 0.5, 1.0, 1.5 });
            Assert.Equal((0.5, 1.0, 1.5), (manifest.Scale.X, manifest.Scale.Y, manifest.Scale.Z));
            Assert.Equal(0.0, manifest.Offset.Y);
        }
    }
}
