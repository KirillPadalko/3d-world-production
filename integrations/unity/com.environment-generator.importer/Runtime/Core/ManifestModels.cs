// Typed view of scene-manifest.json v1.0 (schemas/scene-manifest.schema.json).
//
// The manifest uses the location frame of LocationBlueprint v1.0, which is
// Unity's frame: metres, +X east, +Y up, +Z north (forward), left-handed,
// rotationDeg applied Z, then X, then Y (Quaternion.Euler). Values are used
// as they are; nothing in this package swaps or negates axes.
//
// This file has no UnityEngine dependency so it can be unit-tested with dotnet.

using System.Collections.Generic;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace EnvGen.Importer.Core
{
    public sealed class SceneManifest
    {
        [JsonProperty("manifestVersion")] public string ManifestVersion { get; set; } = "";
        [JsonProperty("generator")] public GeneratorInfo Generator { get; set; } = new GeneratorInfo();
        [JsonProperty("coordinateSystem")] public CoordinateSystemInfo CoordinateSystem { get; set; } = new CoordinateSystemInfo();
        [JsonProperty("source")] public ManifestSource Source { get; set; } = new ManifestSource();
        [JsonProperty("extent")] public Extent Extent { get; set; } = new Extent();

        /// <summary>Heightfield, or null when terrain generation was disabled.</summary>
        [JsonProperty("terrain")] public TerrainGrid Terrain { get; set; }

        /// <summary>Lighting and weather, or null when disabled.</summary>
        [JsonProperty("atmosphere")] public AtmosphereSettings Atmosphere { get; set; }

        [JsonProperty("entities")] public List<ManifestEntity> Entities { get; set; } = new List<ManifestEntity>();
        [JsonProperty("annotations")] public Annotations Annotations { get; set; } = new Annotations();
        [JsonProperty("statistics")] public ManifestStatistics Statistics { get; set; } = new ManifestStatistics();
        [JsonProperty("contentHash")] public string ContentHash { get; set; } = "";
    }

    public sealed class GeneratorInfo
    {
        [JsonProperty("name")] public string Name { get; set; } = "";
        [JsonProperty("version")] public string Version { get; set; } = "";
    }

    public sealed class CoordinateSystemInfo
    {
        [JsonProperty("unit")] public string Unit { get; set; } = "";
        [JsonProperty("upAxis")] public string UpAxis { get; set; } = "";
        [JsonProperty("eastAxis")] public string EastAxis { get; set; } = "";
        [JsonProperty("northAxis")] public string NorthAxis { get; set; } = "";
        [JsonProperty("handedness")] public string Handedness { get; set; } = "";
        [JsonProperty("yawConvention")] public string YawConvention { get; set; } = "";
        [JsonProperty("rotationOrder")] public string RotationOrder { get; set; } = "";
        [JsonProperty("forwardAxis")] public string ForwardAxis { get; set; } = "";
        [JsonProperty("origin")] public string Origin { get; set; } = "";
    }

    public sealed class ManifestSource
    {
        [JsonProperty("locationId")] public string LocationId { get; set; } = "";
        [JsonProperty("locationName")] public string LocationName { get; set; } = "";
        [JsonProperty("recipeId")] public string RecipeId { get; set; } = "";
        [JsonProperty("overridesId")] public string OverridesId { get; set; }
        [JsonProperty("registryId")] public string RegistryId { get; set; } = "";
        [JsonProperty("seed")] public long Seed { get; set; }
        [JsonProperty("generatorSeeds")] public Dictionary<string, long> GeneratorSeeds { get; set; } = new Dictionary<string, long>();
        [JsonProperty("controls")] public GenerationControls Controls { get; set; } = new GenerationControls();
        [JsonProperty("inputFingerprint")] public string InputFingerprint { get; set; } = "";
    }

    public sealed class GenerationControls
    {
        [JsonProperty("structuralSimilarity")] public double StructuralSimilarity { get; set; }
        [JsonProperty("visualVariation")] public double VisualVariation { get; set; }
        [JsonProperty("detailDensity")] public double DetailDensity { get; set; }
        [JsonProperty("abandonment")] public double Abandonment { get; set; }
    }

    public sealed class Extent
    {
        [JsonProperty("widthM")] public double WidthM { get; set; }
        [JsonProperty("depthM")] public double DepthM { get; set; }
    }

    /// <summary>Regular heightfield; <c>Heights[row][column]</c>, row 0 on the south edge (z = origin z).</summary>
    public sealed class TerrainGrid
    {
        /// <summary><c>[x, z]</c> of sample (column 0, row 0).</summary>
        [JsonProperty("origin")] public double[] Origin { get; set; } = { 0.0, 0.0 };
        [JsonProperty("cellSizeM")] public double CellSizeM { get; set; }
        [JsonProperty("columns")] public int Columns { get; set; }
        [JsonProperty("rows")] public int Rows { get; set; }
        [JsonProperty("heights")] public double[][] Heights { get; set; } = new double[0][];
        [JsonProperty("minElevationM")] public double MinElevationM { get; set; }
        [JsonProperty("maxElevationM")] public double MaxElevationM { get; set; }
        [JsonProperty("groundCover")] public string GroundCover { get; set; } = "";

        public double SizeX => CellSizeM * (Columns - 1);
        public double SizeZ => CellSizeM * (Rows - 1);
    }

    public sealed class AtmosphereSettings
    {
        [JsonProperty("timeOfDay")] public string TimeOfDay { get; set; } = "";
        [JsonProperty("weather")] public string Weather { get; set; } = "";
        [JsonProperty("season")] public string Season { get; set; } = "";
        [JsonProperty("keyLightAzimuthDeg")] public double KeyLightAzimuthDeg { get; set; }
        [JsonProperty("keyLightElevationDeg")] public double KeyLightElevationDeg { get; set; }

        /// <summary>Unit vector from the light into the scene (location frame).</summary>
        [JsonProperty("keyLightDirection")] public double[] KeyLightDirection { get; set; } = { 0.0, -1.0, 0.0 };
        [JsonProperty("keyLightColor")] public double[] KeyLightColor { get; set; } = { 1.0, 1.0, 1.0 };
        [JsonProperty("keyLightIntensity")] public double KeyLightIntensity { get; set; }
        [JsonProperty("ambientColor")] public double[] AmbientColor { get; set; } = { 1.0, 1.0, 1.0 };
        [JsonProperty("ambientIntensity")] public double AmbientIntensity { get; set; }
        [JsonProperty("fogColor")] public double[] FogColor { get; set; } = { 1.0, 1.0, 1.0 };

        /// <summary>Exponential fog coefficient (per metre).</summary>
        [JsonProperty("fogDensity")] public double FogDensity { get; set; }
        [JsonProperty("cloudCover")] public double CloudCover { get; set; }
        [JsonProperty("precipitation")] public string Precipitation { get; set; } = "";
        [JsonProperty("precipitationIntensity")] public double PrecipitationIntensity { get; set; }
        [JsonProperty("windSpeedMps")] public double WindSpeedMps { get; set; }
        [JsonProperty("windDirectionDeg")] public double WindDirectionDeg { get; set; }
        [JsonProperty("foliage")] public string Foliage { get; set; } = "";
        [JsonProperty("styleTheme")] public string StyleTheme { get; set; } = "";
        [JsonProperty("weathering")] public double Weathering { get; set; }
        [JsonProperty("groundWetness")] public double GroundWetness { get; set; }
        [JsonProperty("saturation")] public double Saturation { get; set; } = 1.0;
        [JsonProperty("contrast")] public double Contrast { get; set; } = 1.0;
        [JsonProperty("abandonment")] public double Abandonment { get; set; }
        [JsonProperty("vegetationCondition")] public double VegetationCondition { get; set; } = 1.0;
        [JsonProperty("palette")] public List<PaletteColor> Palette { get; set; } = new List<PaletteColor>();
    }

    public sealed class PaletteColor
    {
        [JsonProperty("role")] public string Role { get; set; } = "";
        [JsonProperty("color")] public string Color { get; set; } = "";
    }

    public sealed class ManifestEntity
    {
        [JsonProperty("id")] public string Id { get; set; } = "";

        /// <summary>terrain, water, road, building, fence, infrastructure, vegetation or prop.</summary>
        [JsonProperty("category")] public string Category { get; set; } = "";
        [JsonProperty("kind")] public string Kind { get; set; } = "";
        [JsonProperty("archetypeId")] public string ArchetypeId { get; set; } = "";
        [JsonProperty("assetRef")] public string AssetRef { get; set; } = "";
        [JsonProperty("variant")] public int Variant { get; set; }
        [JsonProperty("placeholder")] public bool Placeholder { get; set; }
        [JsonProperty("transform")] public EntityTransform Transform { get; set; } = new EntityTransform();
        [JsonProperty("dimensions")] public Dimensions Dimensions { get; set; } = new Dimensions();

        /// <summary>World-space polyline or polygon (roads, cables, water), else null.</summary>
        [JsonProperty("geometry")] public EntityGeometry Geometry { get; set; }
        [JsonProperty("parameters")] public Dictionary<string, JToken> Parameters { get; set; } = new Dictionary<string, JToken>();
        [JsonProperty("tags")] public List<string> Tags { get; set; } = new List<string>();
        [JsonProperty("provenance")] public EntityProvenance Provenance { get; set; } = new EntityProvenance();

        public bool TryGetNumber(string key, out double value)
        {
            value = 0.0;
            if (Parameters == null || !Parameters.TryGetValue(key, out var token) || token == null)
            {
                return false;
            }
            if (token.Type == JTokenType.Float || token.Type == JTokenType.Integer)
            {
                value = token.Value<double>();
                return true;
            }
            return false;
        }
    }

    public sealed class EntityTransform
    {
        /// <summary><c>[x, y, z]</c>: east, up, north in metres.</summary>
        [JsonProperty("position")] public double[] Position { get; set; } = { 0.0, 0.0, 0.0 };

        /// <summary>Euler degrees for <c>Quaternion.Euler(x, y, z)</c>; y is the yaw.</summary>
        [JsonProperty("rotationDeg")] public double[] RotationDeg { get; set; } = { 0.0, 0.0, 0.0 };

        /// <summary>Along local X (width), Y (height), Z (depth), relative to the archetype size.</summary>
        [JsonProperty("scale")] public double[] Scale { get; set; } = { 1.0, 1.0, 1.0 };
    }

    /// <summary>World-space size after scaling: width (local X), depth (local Z), height (local Y).</summary>
    public sealed class Dimensions
    {
        [JsonProperty("widthM")] public double WidthM { get; set; }
        [JsonProperty("depthM")] public double DepthM { get; set; }
        [JsonProperty("heightM")] public double HeightM { get; set; }
    }

    public sealed class EntityGeometry
    {
        /// <summary><c>polyline</c> or <c>polygon</c>.</summary>
        [JsonProperty("type")] public string Type { get; set; } = "";

        /// <summary>World <c>[x, y, z]</c> points.</summary>
        [JsonProperty("points")] public double[][] Points { get; set; } = new double[0][];

        /// <summary>Ground width of a polyline (roads); null for overhead lines.</summary>
        [JsonProperty("widthM")] public double? WidthM { get; set; }
    }

    public sealed class EntityProvenance
    {
        [JsonProperty("generator")] public string Generator { get; set; } = "";
        [JsonProperty("implementation")] public string Implementation { get; set; } = "";
        [JsonProperty("rule")] public string Rule { get; set; } = "";
        [JsonProperty("sourceFeature")] public string SourceFeature { get; set; }
        [JsonProperty("overrides")] public List<string> Overrides { get; set; } = new List<string>();
    }

    public sealed class ManifestStatistics
    {
        [JsonProperty("entityCount")] public int EntityCount { get; set; }
        [JsonProperty("byCategory")] public Dictionary<string, int> ByCategory { get; set; } = new Dictionary<string, int>();
        [JsonProperty("byGenerator")] public Dictionary<string, int> ByGenerator { get; set; } = new Dictionary<string, int>();
        [JsonProperty("placeholderCount")] public int PlaceholderCount { get; set; }
    }

    // ------------------------------------------------------------------ annotations
    // Landmarks and gameplay annotations copied from the LocationBlueprint.

    public sealed class Annotations
    {
        [JsonProperty("landmarks")] public List<Landmark> Landmarks { get; set; } = new List<Landmark>();
        [JsonProperty("gameplay")] public Gameplay Gameplay { get; set; } = new Gameplay();
    }

    public sealed class Landmark
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("label")] public string Label { get; set; }
        [JsonProperty("landmarkType")] public string LandmarkType { get; set; } = "";
        [JsonProperty("position")] public double[] Position { get; set; } = { 0.0, 0.0, 0.0 };
        [JsonProperty("importance")] public double Importance { get; set; }
        [JsonProperty("visibility")] public string Visibility { get; set; } = "";
        [JsonProperty("visibilityRadiusM")] public double? VisibilityRadiusM { get; set; }
        [JsonProperty("linkedEntityId")] public string LinkedEntityId { get; set; }
        [JsonProperty("gameplayRoles")] public List<string> GameplayRoles { get; set; } = new List<string>();
    }

    public sealed class Gameplay
    {
        [JsonProperty("navigationAreas")] public List<NavigationArea> NavigationAreas { get; set; } = new List<NavigationArea>();
        [JsonProperty("coverZones")] public List<CoverZone> CoverZones { get; set; } = new List<CoverZone>();
        [JsonProperty("combatZones")] public List<CombatZone> CombatZones { get; set; } = new List<CombatZone>();
        [JsonProperty("spawnClearances")] public List<SpawnClearance> SpawnClearances { get; set; } = new List<SpawnClearance>();
        [JsonProperty("lineOfSight")] public List<LineOfSight> LineOfSight { get; set; } = new List<LineOfSight>();
    }

    public sealed class NavigationArea
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("label")] public string Label { get; set; }

        /// <summary><c>walkable</c> or <c>blocked</c>.</summary>
        [JsonProperty("areaType")] public string AreaType { get; set; } = "";

        /// <summary><c>[x, z]</c> ring, or null when only entity IDs are given.</summary>
        [JsonProperty("polygon")] public double[][] Polygon { get; set; }
        [JsonProperty("entityIds")] public List<string> EntityIds { get; set; } = new List<string>();
        [JsonProperty("reason")] public string Reason { get; set; }
    }

    public sealed class CoverZone
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("label")] public string Label { get; set; }
        [JsonProperty("polygon")] public double[][] Polygon { get; set; } = new double[0][];

        /// <summary><c>none</c>, <c>slow</c> or <c>block</c>.</summary>
        [JsonProperty("movement")] public string Movement { get; set; } = "none";

        /// <summary><c>none</c>, <c>partial</c> or <c>full</c>.</summary>
        [JsonProperty("projectileCover")] public string ProjectileCover { get; set; } = "partial";

        /// <summary><c>none</c>, <c>partial</c> or <c>full</c> visual occlusion.</summary>
        [JsonProperty("vision")] public string Vision { get; set; } = "partial";
        [JsonProperty("linkedEntityIds")] public List<string> LinkedEntityIds { get; set; } = new List<string>();
        [JsonProperty("notes")] public string Notes { get; set; }
    }

    public sealed class CombatZone
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("label")] public string Label { get; set; }
        [JsonProperty("polygon")] public double[][] Polygon { get; set; } = new double[0][];
        [JsonProperty("intensity")] public string Intensity { get; set; } = "medium";
        [JsonProperty("engagementRange")] public string EngagementRange { get; set; } = "mixed";
        [JsonProperty("notes")] public string Notes { get; set; }
    }

    public sealed class SpawnClearance
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("label")] public string Label { get; set; }

        /// <summary><c>[x, z]</c>.</summary>
        [JsonProperty("position")] public double[] Position { get; set; } = { 0.0, 0.0 };
        [JsonProperty("radiusM")] public double RadiusM { get; set; }
        [JsonProperty("role")] public string Role { get; set; } = "spawn";
    }

    public sealed class LineOfSight
    {
        [JsonProperty("id")] public string Id { get; set; } = "";
        [JsonProperty("label")] public string Label { get; set; }
        [JsonProperty("fromPosition")] public double[] FromPosition { get; set; } = { 0.0, 0.0, 0.0 };
        [JsonProperty("toPosition")] public double[] ToPosition { get; set; } = { 0.0, 0.0, 0.0 };

        /// <summary><c>clear</c>, <c>partial</c> or <c>blocked</c>.</summary>
        [JsonProperty("expected")] public string Expected { get; set; } = "";
        [JsonProperty("notes")] public string Notes { get; set; }
    }
}
