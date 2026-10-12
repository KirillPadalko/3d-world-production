// Engine-free import decisions: which asset represents an entity, how an
// entity is built, and what a re-import changes in an existing scene.

using System;
using System.Collections.Generic;
using System.Linq;

namespace EnvGen.Importer.Core
{
    /// <summary>How an entity becomes scene content.</summary>
    public enum EntityShape
    {
        /// <summary>A prefab (or placeholder box) at the entity transform.</summary>
        Object,

        /// <summary>A generated road ribbon mesh (polyline with a ground width).</summary>
        RoadRibbon,

        /// <summary>A generated disc mesh (road junction).</summary>
        RoadJunction,

        /// <summary>A generated flat polygon mesh (water surface).</summary>
        WaterSurface,

        /// <summary>A line through support points (overhead cable).</summary>
        Cable,

        /// <summary>Represented by the Unity Terrain, not by an object.</summary>
        Terrain,
    }

    public static class EntityShapes
    {
        public static EntityShape Classify(ManifestEntity entity)
        {
            if (entity.Category == "terrain")
            {
                return EntityShape.Terrain;
            }
            EntityGeometry geometry = entity.Geometry;
            if (geometry != null && geometry.Type == "polygon")
            {
                return EntityShape.WaterSurface;
            }
            if (geometry != null && geometry.Type == "polyline")
            {
                return geometry.WidthM.HasValue && geometry.WidthM.Value > 0 ? EntityShape.RoadRibbon : EntityShape.Cable;
            }
            if (entity.Category == "road" && entity.Kind == "junction")
            {
                return EntityShape.RoadJunction;
            }
            return EntityShape.Object;
        }
    }

    public enum BindingSource
    {
        /// <summary>The registry binds the entity's archetypeId.</summary>
        Archetype,

        /// <summary>The registry binds the entity's category and kind.</summary>
        Kind,

        /// <summary>Nothing is bound; a placeholder is used.</summary>
        Placeholder,
    }

    public sealed class BindingChoice<T> where T : class
    {
        public BindingSource Source { get; set; }

        /// <summary>The chosen asset, or null for a placeholder.</summary>
        public T Asset { get; set; }

        /// <summary>Index into the bound variants (<c>variant % count</c>).</summary>
        public int VariantIndex { get; set; }
    }

    public static class ArchetypeLookup
    {
        public static string KindKey(string category, string kind) => category + "/" + kind;

        /// <summary>
        /// Exact archetype binding first, then category/kind binding, else placeholder.
        /// Among bound variants the manifest <c>variant</c> picks <c>variant % count</c>, so the
        /// choice is stable across re-imports.
        /// </summary>
        public static BindingChoice<T> Choose<T>(
            ManifestEntity entity,
            IReadOnlyDictionary<string, IReadOnlyList<T>> byArchetype,
            IReadOnlyDictionary<string, IReadOnlyList<T>> byKind)
            where T : class
        {
            if (TryPick(byArchetype, entity.ArchetypeId, entity.Variant, out T asset, out int index))
            {
                return new BindingChoice<T> { Source = BindingSource.Archetype, Asset = asset, VariantIndex = index };
            }
            if (TryPick(byKind, KindKey(entity.Category, entity.Kind), entity.Variant, out asset, out index))
            {
                return new BindingChoice<T> { Source = BindingSource.Kind, Asset = asset, VariantIndex = index };
            }
            return new BindingChoice<T> { Source = BindingSource.Placeholder };
        }

        private static bool TryPick<T>(
            IReadOnlyDictionary<string, IReadOnlyList<T>> table, string key, int variant, out T asset, out int index)
            where T : class
        {
            asset = null;
            index = 0;
            if (table == null || key == null || !table.TryGetValue(key, out IReadOnlyList<T> options) || options == null)
            {
                return false;
            }
            var usable = options.Where(o => o != null).ToList();
            if (usable.Count == 0)
            {
                return false;
            }
            index = ((variant % usable.Count) + usable.Count) % usable.Count;
            asset = usable[index];
            return true;
        }
    }

    /// <summary>What a previous import left in the scene for one entity.</summary>
    public sealed class ExistingEntityState
    {
        public string Id { get; set; } = "";
        public string Category { get; set; } = "";
        public string Kind { get; set; } = "";
        public string ArchetypeId { get; set; } = "";
        public int Variant { get; set; }
    }

    public sealed class ReimportPlan
    {
        /// <summary>New entities.</summary>
        public List<string> Create { get; } = new List<string>();

        /// <summary>Same archetype, kind and variant: only transform and metadata change.</summary>
        public List<string> Update { get; } = new List<string>();

        /// <summary>Archetype, kind or variant changed: the visual is rebuilt.</summary>
        public List<string> Replace { get; } = new List<string>();

        /// <summary>No longer in the manifest.</summary>
        public List<string> Remove { get; } = new List<string>();
    }

    public static class ReimportPlanner
    {
        /// <summary>Match scene content to manifest entities by stable entity ID.</summary>
        public static ReimportPlan Plan(IEnumerable<ExistingEntityState> existing, IEnumerable<ManifestEntity> incoming)
        {
            var current = new Dictionary<string, ExistingEntityState>(StringComparer.Ordinal);
            foreach (ExistingEntityState state in existing)
            {
                current[state.Id] = state;
            }
            var plan = new ReimportPlan();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (ManifestEntity entity in incoming.OrderBy(e => e.Id, StringComparer.Ordinal))
            {
                seen.Add(entity.Id);
                if (!current.TryGetValue(entity.Id, out ExistingEntityState state))
                {
                    plan.Create.Add(entity.Id);
                }
                else if (state.ArchetypeId == entity.ArchetypeId && state.Kind == entity.Kind
                         && state.Category == entity.Category && state.Variant == entity.Variant)
                {
                    plan.Update.Add(entity.Id);
                }
                else
                {
                    plan.Replace.Add(entity.Id);
                }
            }
            plan.Remove.AddRange(current.Keys.Where(id => !seen.Contains(id)).OrderBy(id => id, StringComparer.Ordinal));
            return plan;
        }
    }

    /// <summary>Scale and offset that make an asset's bounds match an entity's dimensions.</summary>
    public struct FitResult
    {
        public Vec3 Scale;

        /// <summary>Local position that puts the scaled bounds' bottom centre on the pivot.</summary>
        public Vec3 Offset;
    }

    public enum FitMode
    {
        /// <summary>Use the manifest scale; the asset is modelled at the archetype's nominal size, pivot at the bottom centre.</summary>
        ManifestScale,

        /// <summary>Scale each axis so the asset bounds match width, height and depth.</summary>
        FitDimensions,

        /// <summary>Scale uniformly so the asset height matches (trees, props).</summary>
        FitHeightUniform,
    }

    public static class AssetFitting
    {
        /// <summary>
        /// Compute scale and offset for an asset whose unscaled local bounds are
        /// <paramref name="boundsCenter"/> / <paramref name="boundsSize"/>. Dimensions are
        /// (width = X, height = Y, depth = Z). Degenerate axes keep scale 1.
        /// </summary>
        public static FitResult Fit(FitMode mode, Vec3 boundsCenter, Vec3 boundsSize, Dimensions dimensions, double[] manifestScale)
        {
            Vec3 scale;
            switch (mode)
            {
                case FitMode.FitDimensions:
                    scale = new Vec3(
                        Ratio(dimensions.WidthM, boundsSize.X),
                        Ratio(dimensions.HeightM, boundsSize.Y),
                        Ratio(dimensions.DepthM, boundsSize.Z));
                    break;
                case FitMode.FitHeightUniform:
                    double s = Ratio(dimensions.HeightM, boundsSize.Y);
                    scale = new Vec3(s, s, s);
                    break;
                default:
                    return new FitResult { Scale = new Vec3(manifestScale[0], manifestScale[1], manifestScale[2]), Offset = new Vec3(0, 0, 0) };
            }
            // Move the scaled bounds so their bottom centre sits on the entity pivot.
            Vec3 bottomCentre = new Vec3(boundsCenter.X, boundsCenter.Y - boundsSize.Y / 2.0, boundsCenter.Z);
            var offset = new Vec3(-bottomCentre.X * scale.X, -bottomCentre.Y * scale.Y, -bottomCentre.Z * scale.Z);
            return new FitResult { Scale = scale, Offset = offset };
        }

        private static double Ratio(double target, double size) => size > 1e-6 && target > 0 ? target / size : 1.0;
    }
}
