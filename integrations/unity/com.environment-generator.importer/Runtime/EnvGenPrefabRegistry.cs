using System;
using System.Collections.Generic;
using EnvGen.Importer.Core;
using UnityEngine;

namespace EnvGen.Importer
{
    /// <summary>
    /// Maps manifest archetypes to your prefabs and materials. Lookup order for an
    /// entity: its exact <c>archetypeId</c>, then its <c>category/kind</c>, else a
    /// placeholder box sized to the entity. Several prefabs per binding are variants;
    /// the manifest <c>variant</c> picks one deterministically.
    /// </summary>
    [CreateAssetMenu(menuName = "Environment Generator/Prefab Registry", fileName = "EnvGenPrefabRegistry")]
    public sealed class EnvGenPrefabRegistry : ScriptableObject
    {
        [Serializable]
        public sealed class ArchetypeBinding
        {
            [Tooltip("Manifest archetypeId, e.g. building.dacha.wooden_house_small.")]
            public string archetypeId = "";
            public GameObject[] prefabs = new GameObject[0];

            [Tooltip("ManifestScale: the prefab is modelled at the registry size with its pivot at the bottom centre. "
                     + "FitDimensions: scale each axis to the entity size. FitHeightUniform: keep proportions, match the height.")]
            public FitMode fit = FitMode.FitDimensions;
        }

        [Serializable]
        public sealed class KindBinding
        {
            [Tooltip("building, fence, infrastructure, vegetation, prop ...")]
            public string category = "";

            [Tooltip("Entity kind, e.g. house, tree, utility_pole.")]
            public string kind = "";
            public GameObject[] prefabs = new GameObject[0];
            public FitMode fit = FitMode.FitDimensions;
        }

        [Serializable]
        public sealed class MaterialBinding
        {
            [Tooltip("archetypeId (road.profile.gravel) or category/kind (road/dirt_track, water/pond).")]
            public string key = "";
            public Material material;
        }

        [Serializable]
        public sealed class TerrainLayerBinding
        {
            [Tooltip("Manifest terrain.groundCover (grass, dirt, sand, ...) or a terrain archetypeId.")]
            public string groundCover = "";
            public TerrainLayer layer;
        }

        public List<ArchetypeBinding> archetypes = new List<ArchetypeBinding>();
        public List<KindBinding> kinds = new List<KindBinding>();

        [Tooltip("Materials for generated road, junction and water meshes.")]
        public List<MaterialBinding> materials = new List<MaterialBinding>();
        public List<TerrainLayerBinding> terrainLayers = new List<TerrainLayerBinding>();

        public Material defaultRoadMaterial;
        public Material defaultWaterMaterial;
        public Material cableMaterial;

        [Tooltip("Material for placeholder boxes (unbound archetypes).")]
        public Material placeholderMaterial;

        [Min(0.001f)] public float cableWidth = 0.03f;

        public Dictionary<string, IReadOnlyList<GameObject>> ArchetypeTable()
        {
            var table = new Dictionary<string, IReadOnlyList<GameObject>>(StringComparer.Ordinal);
            foreach (ArchetypeBinding binding in archetypes)
            {
                if (!string.IsNullOrEmpty(binding.archetypeId) && !table.ContainsKey(binding.archetypeId))
                {
                    table[binding.archetypeId] = binding.prefabs;
                }
            }
            return table;
        }

        public Dictionary<string, IReadOnlyList<GameObject>> KindTable()
        {
            var table = new Dictionary<string, IReadOnlyList<GameObject>>(StringComparer.Ordinal);
            foreach (KindBinding binding in kinds)
            {
                string key = ArchetypeLookup.KindKey(binding.category, binding.kind);
                if (!string.IsNullOrEmpty(binding.kind) && !table.ContainsKey(key))
                {
                    table[key] = binding.prefabs;
                }
            }
            return table;
        }

        public FitMode FitFor(BindingSource source, ManifestEntity entity)
        {
            if (source == BindingSource.Archetype)
            {
                foreach (ArchetypeBinding binding in archetypes)
                {
                    if (binding.archetypeId == entity.ArchetypeId)
                    {
                        return binding.fit;
                    }
                }
            }
            if (source == BindingSource.Kind)
            {
                foreach (KindBinding binding in kinds)
                {
                    if (binding.category == entity.Category && binding.kind == entity.Kind)
                    {
                        return binding.fit;
                    }
                }
            }
            return FitMode.FitDimensions;
        }

        /// <summary>Material for a generated mesh: archetype, then category/kind, else null.</summary>
        public Material MaterialFor(ManifestEntity entity)
        {
            string kindKey = ArchetypeLookup.KindKey(entity.Category, entity.Kind);
            Material byKind = null;
            foreach (MaterialBinding binding in materials)
            {
                if (binding.material == null)
                {
                    continue;
                }
                if (binding.key == entity.ArchetypeId)
                {
                    return binding.material;
                }
                if (byKind == null && binding.key == kindKey)
                {
                    byKind = binding.material;
                }
            }
            return byKind;
        }

        public TerrainLayer LayerFor(string groundCover, string terrainArchetypeId)
        {
            TerrainLayer byCover = null;
            foreach (TerrainLayerBinding binding in terrainLayers)
            {
                if (binding.layer == null)
                {
                    continue;
                }
                if (!string.IsNullOrEmpty(terrainArchetypeId) && binding.groundCover == terrainArchetypeId)
                {
                    return binding.layer;
                }
                if (byCover == null && binding.groundCover == groundCover)
                {
                    byCover = binding.layer;
                }
            }
            return byCover;
        }
    }
}
