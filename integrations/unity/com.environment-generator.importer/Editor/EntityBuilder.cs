using System;
using System.Collections.Generic;
using System.Linq;
using EnvGen.Importer.Core;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace EnvGen.Importer.Editor
{
    /// <summary>
    /// Creates, updates and removes entity objects. Each entity is a GameObject named
    /// after its stable ID that carries the manifest transform exactly, with an
    /// <see cref="EnvGenEntity"/> component; the asset sits in a child named "visual".
    /// </summary>
    internal static class EntityBuilder
    {
        public const string VisualName = "visual";

        public static void Sync(Transform root, SceneManifest manifest, EnvGenPrefabRegistry registry, ImportSettings settings, ImportReport report)
        {
            Transform entitiesGroup = ManifestSceneImporter.Group(root, ManifestSceneImporter.EntitiesGroup);
            var existing = new Dictionary<string, EnvGenEntity>(StringComparer.Ordinal);
            foreach (EnvGenEntity component in entitiesGroup.GetComponentsInChildren<EnvGenEntity>(true))
            {
                if (existing.ContainsKey(component.entityId))
                {
                    report.Warnings.Add($"Several objects carry entity id '{component.entityId}'; only one is updated.");
                    continue;
                }
                existing[component.entityId] = component;
            }

            List<ManifestEntity> entities = manifest.Entities
                .Where(e => EntityShapes.Classify(e) != EntityShape.Terrain)
                .ToList();
            ReimportPlan plan = ReimportPlanner.Plan(
                existing.Values.Select(e => new ExistingEntityState
                {
                    Id = e.entityId,
                    Category = e.category,
                    Kind = e.kind,
                    ArchetypeId = e.archetypeId,
                    Variant = e.variant,
                }),
                entities);
            foreach (string id in plan.Remove)
            {
                Undo.DestroyObjectImmediate(existing[id].gameObject);
                existing.Remove(id);
            }
            report.Removed += plan.Remove.Count;
            report.Updated += plan.Update.Count;
            report.Replaced += plan.Replace.Count;
            report.Created += plan.Create.Count;

            Dictionary<string, IReadOnlyList<GameObject>> byArchetype =
                registry != null ? registry.ArchetypeTable() : new Dictionary<string, IReadOnlyList<GameObject>>();
            Dictionary<string, IReadOnlyList<GameObject>> byKind =
                registry != null ? registry.KindTable() : new Dictionary<string, IReadOnlyList<GameObject>>();

            for (int i = 0; i < entities.Count; i++)
            {
                ManifestEntity entity = entities[i];
                if (i % 25 == 0)
                {
                    EditorUtility.DisplayProgressBar("Environment Generator", $"{entity.Id} ({i + 1}/{entities.Count})", (float)i / entities.Count);
                }
                Transform group = ManifestSceneImporter.Group(entitiesGroup, entity.Category);
                if (!existing.TryGetValue(entity.Id, out EnvGenEntity component))
                {
                    var node = new GameObject(entity.Id);
                    Undo.RegisterCreatedObjectUndo(node, "Create entity");
                    node.transform.SetParent(group, false);
                    component = node.AddComponent<EnvGenEntity>();
                }
                else if (component.transform.parent != group)
                {
                    Undo.SetTransformParent(component.transform, group, "Move entity");
                }

                Transform transform = component.transform;
                Undo.RecordObject(transform, "Place entity");
                transform.name = entity.Id;
                transform.localPosition = ManifestSceneImporter.ToVector3(entity.Transform.Position);
                transform.localRotation = Quaternion.Euler(ManifestSceneImporter.ToVector3(entity.Transform.RotationDeg));
                transform.localScale = Vector3.one;

                Transform oldVisual = transform.Find(VisualName);
                if (oldVisual != null)
                {
                    Undo.DestroyObjectImmediate(oldVisual.gameObject);
                }
                string binding = BuildVisual(transform, entity, registry, byArchetype, byKind, settings, report);
                WriteMetadata(component, entity, binding);
            }
        }

        private static string BuildVisual(
            Transform node,
            ManifestEntity entity,
            EnvGenPrefabRegistry registry,
            Dictionary<string, IReadOnlyList<GameObject>> byArchetype,
            Dictionary<string, IReadOnlyList<GameObject>> byKind,
            ImportSettings settings,
            ImportReport report)
        {
            Vec3 origin = Vec3.FromArray(entity.Transform.Position);
            Material material = registry != null ? registry.MaterialFor(entity) : null;
            switch (EntityShapes.Classify(entity))
            {
                case EntityShape.RoadRibbon:
                {
                    List<Vec3> points = entity.Geometry.Points.Select(Vec3.FromArray).ToList();
                    MeshData mesh = RibbonMeshBuilder.Build(points, entity.Geometry.WidthM.Value, settings.surfaceLift);
                    AddMesh(node, mesh.RelativeTo(origin), entity.Id, material ?? Fallback(registry != null ? registry.defaultRoadMaterial : null), settings.addColliders);
                    report.GeneratedMeshes++;
                    return "generated road";
                }
                case EntityShape.RoadJunction:
                {
                    double radius = Math.Max(entity.Dimensions.WidthM, 0.5) / 2.0;
                    // Slightly above the road ribbons so the junction disc wins the depth test.
                    MeshData mesh = SurfaceMeshBuilder.Disc(new Vec3(0, 0, 0), radius, 24, settings.surfaceLift + 0.005);
                    AddMesh(node, mesh, entity.Id, material ?? Fallback(registry != null ? registry.defaultRoadMaterial : null), settings.addColliders);
                    report.GeneratedMeshes++;
                    return "generated junction";
                }
                case EntityShape.WaterSurface:
                {
                    MeshData mesh = SurfaceMeshBuilder.Polygon(entity.Geometry.Points, 0.0);
                    AddMesh(node, mesh.RelativeTo(origin), entity.Id, material ?? Fallback(registry != null ? registry.defaultWaterMaterial : null), false);
                    report.GeneratedMeshes++;
                    return "generated water";
                }
                case EntityShape.Cable:
                    AddCable(node, entity, origin, registry, settings);
                    report.GeneratedMeshes++;
                    return "generated cable";
                default:
                    return AddObject(node, entity, registry, byArchetype, byKind, settings, report);
            }
        }

        private static string AddObject(
            Transform node,
            ManifestEntity entity,
            EnvGenPrefabRegistry registry,
            Dictionary<string, IReadOnlyList<GameObject>> byArchetype,
            Dictionary<string, IReadOnlyList<GameObject>> byKind,
            ImportSettings settings,
            ImportReport report)
        {
            BindingChoice<GameObject> choice = ArchetypeLookup.Choose(entity, byArchetype, byKind);
            GameObject visual = choice.Asset != null ? PrefabUtility.InstantiatePrefab(choice.Asset, node) as GameObject : null;
            if (visual == null)
            {
                AddPlaceholder(node, entity, registry, settings);
                report.Placeholders++;
                report.UnboundArchetypes.Add(entity.ArchetypeId);
                return "placeholder";
            }
            Undo.RegisterCreatedObjectUndo(visual, "Create visual");
            visual.name = VisualName;
            visual.transform.localPosition = Vector3.zero;
            visual.transform.localRotation = Quaternion.identity;
            visual.transform.localScale = Vector3.one;

            FitMode mode = registry.FitFor(choice.Source, entity);
            LocalBounds(node, visual, out Vector3 center, out Vector3 size);
            FitResult fit = AssetFitting.Fit(
                mode,
                new Vec3(center.x, center.y, center.z),
                new Vec3(size.x, size.y, size.z),
                entity.Dimensions,
                entity.Transform.Scale);
            visual.transform.localScale = ManifestSceneImporter.ToVector3(fit.Scale);
            visual.transform.localPosition = ManifestSceneImporter.ToVector3(fit.Offset);
            return choice.Source == BindingSource.Archetype ? "archetype" : "kind";
        }

        /// <summary>Bounds of every renderer under <paramref name="visual"/> in <paramref name="node"/> space.</summary>
        private static void LocalBounds(Transform node, GameObject visual, out Vector3 center, out Vector3 size)
        {
            bool any = false;
            var bounds = new Bounds();
            foreach (Renderer renderer in visual.GetComponentsInChildren<Renderer>(true))
            {
                Bounds local;
                if (renderer is SkinnedMeshRenderer skinned)
                {
                    local = skinned.localBounds;
                }
                else
                {
                    MeshFilter filter = renderer.GetComponent<MeshFilter>();
                    if (filter == null || filter.sharedMesh == null)
                    {
                        continue;
                    }
                    local = filter.sharedMesh.bounds;
                }
                Matrix4x4 toNode = node.worldToLocalMatrix * renderer.transform.localToWorldMatrix;
                for (int corner = 0; corner < 8; corner++)
                {
                    var offset = new Vector3(
                        (corner & 1) == 0 ? -local.extents.x : local.extents.x,
                        (corner & 2) == 0 ? -local.extents.y : local.extents.y,
                        (corner & 4) == 0 ? -local.extents.z : local.extents.z);
                    Vector3 point = toNode.MultiplyPoint3x4(local.center + offset);
                    if (!any)
                    {
                        bounds = new Bounds(point, Vector3.zero);
                        any = true;
                    }
                    else
                    {
                        bounds.Encapsulate(point);
                    }
                }
            }
            center = any ? bounds.center : Vector3.zero;
            size = any ? bounds.size : Vector3.zero;
        }

        private static void AddPlaceholder(Transform node, ManifestEntity entity, EnvGenPrefabRegistry registry, ImportSettings settings)
        {
            GameObject box = GameObject.CreatePrimitive(PrimitiveType.Cube);
            Undo.RegisterCreatedObjectUndo(box, "Create placeholder");
            box.name = VisualName;
            box.transform.SetParent(node, false);
            float width = Mathf.Max((float)entity.Dimensions.WidthM, 0.05f);
            float height = Mathf.Max((float)entity.Dimensions.HeightM, 0.05f);
            float depth = Mathf.Max((float)entity.Dimensions.DepthM, 0.05f);
            box.transform.localScale = new Vector3(width, height, depth);
            box.transform.localPosition = new Vector3(0f, height / 2f, 0f);
            box.transform.localRotation = Quaternion.identity;
            if (registry != null && registry.placeholderMaterial != null)
            {
                box.GetComponent<MeshRenderer>().sharedMaterial = registry.placeholderMaterial;
            }
            if (!settings.addColliders)
            {
                UnityEngine.Object.DestroyImmediate(box.GetComponent<Collider>());
            }
        }

        private static void AddMesh(Transform node, MeshData data, string name, Material material, bool collider)
        {
            var visual = new GameObject(VisualName);
            Undo.RegisterCreatedObjectUndo(visual, "Create mesh");
            visual.transform.SetParent(node, false);

            // Vertices are relative to the entity position; undo the entity rotation too.
            Quaternion inverse = Quaternion.Inverse(node.localRotation);
            var mesh = new Mesh { name = name };
            if (data.Vertices.Count > 65000)
            {
                mesh.indexFormat = IndexFormat.UInt32;
            }
            mesh.SetVertices(data.Vertices.Select(v => inverse * ManifestSceneImporter.ToVector3(v)).ToList());
            mesh.SetTriangles(data.Triangles, 0);
            mesh.SetUVs(0, data.Uvs.Select(uv => new Vector2((float)uv[0], (float)uv[1])).ToList());
            mesh.RecalculateNormals();
            mesh.RecalculateBounds();

            visual.AddComponent<MeshFilter>().sharedMesh = mesh;
            MeshRenderer renderer = visual.AddComponent<MeshRenderer>();
            if (material != null)
            {
                renderer.sharedMaterial = material;
            }
            if (collider)
            {
                visual.AddComponent<MeshCollider>().sharedMesh = mesh;
            }
        }

        private static void AddCable(Transform node, ManifestEntity entity, Vec3 origin, EnvGenPrefabRegistry registry, ImportSettings settings)
        {
            var visual = new GameObject(VisualName);
            Undo.RegisterCreatedObjectUndo(visual, "Create cable");
            visual.transform.SetParent(node, false);
            double sag = entity.TryGetNumber("sagM", out double value) ? value : 0.0;
            List<Vec3> supports = entity.Geometry.Points.Select(p => Vec3.FromArray(p) - origin).ToList();
            Quaternion inverse = Quaternion.Inverse(node.localRotation);
            Vector3[] positions = CableSag.Sample(supports, sag, settings.cableSamplesPerSpan)
                .Select(p => inverse * ManifestSceneImporter.ToVector3(p))
                .ToArray();

            LineRenderer line = visual.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.positionCount = positions.Length;
            line.SetPositions(positions);
            float width = registry != null ? registry.cableWidth : 0.03f;
            line.startWidth = width;
            line.endWidth = width;
            Material material = registry != null && registry.cableMaterial != null ? registry.cableMaterial : Fallback(null);
            if (material != null)
            {
                line.sharedMaterial = material;
            }
        }

        /// <summary>The given material, else the active render pipeline's default material.</summary>
        private static Material Fallback(Material material)
        {
            if (material != null)
            {
                return material;
            }
            RenderPipelineAsset pipeline = GraphicsSettings.currentRenderPipeline;
            return pipeline != null ? pipeline.defaultMaterial : AssetDatabase.GetBuiltinExtraResource<Material>("Default-Material.mat");
        }

        private static void WriteMetadata(EnvGenEntity component, ManifestEntity entity, string binding)
        {
            Undo.RecordObject(component, "Update entity metadata");
            component.entityId = entity.Id;
            component.category = entity.Category;
            component.kind = entity.Kind;
            component.archetypeId = entity.ArchetypeId;
            component.assetRef = entity.AssetRef;
            component.variant = entity.Variant;
            component.generatorPlaceholder = entity.Placeholder;
            component.binding = binding;
            component.dimensions = new Vector3(
                (float)entity.Dimensions.WidthM, (float)entity.Dimensions.HeightM, (float)entity.Dimensions.DepthM);
            EntityProvenance provenance = entity.Provenance ?? new EntityProvenance();
            component.generator = provenance.Generator;
            component.implementation = provenance.Implementation;
            component.rule = provenance.Rule;
            component.sourceFeature = provenance.SourceFeature ?? "";
            component.overrides = (provenance.Overrides ?? new List<string>()).ToArray();
            component.tags = (entity.Tags ?? new List<string>()).ToArray();
            component.parameters = (entity.Parameters ?? new Dictionary<string, JToken>())
                .OrderBy(p => p.Key, StringComparer.Ordinal)
                .Select(p => new EnvGenEntity.Parameter { key = p.Key, value = ParameterText(p.Value) })
                .ToArray();
        }

        private static string ParameterText(JToken token)
        {
            if (token == null || token.Type == JTokenType.Null)
            {
                return "";
            }
            return token.Type == JTokenType.String ? token.Value<string>() : token.ToString(Formatting.None);
        }
    }
}
