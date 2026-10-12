using System.Linq;
using EnvGen.Importer.Core;
using UnityEditor;
using UnityEngine;

namespace EnvGen.Importer.Editor
{
    /// <summary>
    /// Landmarks and gameplay annotations from the LocationBlueprint, as marker objects
    /// with gizmos. The "Annotations" group is rebuilt on every import.
    /// </summary>
    internal static class AnnotationBuilder
    {
        public static void Build(Transform root, Annotations annotations, Terrain terrain)
        {
            Transform previous = root.Find(ManifestSceneImporter.AnnotationsGroup);
            if (previous != null)
            {
                Undo.DestroyObjectImmediate(previous.gameObject);
            }
            if (annotations == null)
            {
                return;
            }
            Transform group = ManifestSceneImporter.Group(root, ManifestSceneImporter.AnnotationsGroup);
            Transform landmarks = ManifestSceneImporter.Group(group, "Landmarks");
            Transform gameplay = ManifestSceneImporter.Group(group, "Gameplay");

            foreach (Landmark landmark in annotations.Landmarks)
            {
                GameObject go = Child(landmarks, landmark.Id);
                go.transform.localPosition = ManifestSceneImporter.ToVector3(landmark.Position);
                EnvGenLandmark marker = go.AddComponent<EnvGenLandmark>();
                marker.landmarkId = landmark.Id;
                marker.label = landmark.Label ?? "";
                marker.landmarkType = landmark.LandmarkType;
                marker.importance = (float)landmark.Importance;
                marker.visibility = landmark.Visibility;
                marker.visibilityRadius = (float)(landmark.VisibilityRadiusM ?? 0.0);
                marker.linkedEntityId = landmark.LinkedEntityId ?? "";
                marker.gameplayRoles = landmark.GameplayRoles.ToArray();
            }

            Gameplay data = annotations.Gameplay ?? new Gameplay();
            foreach (NavigationArea area in data.NavigationAreas)
            {
                EnvGenGameplayArea marker = Area(root, gameplay, area.Id, area.Polygon, terrain);
                marker.areaKind = EnvGenGameplayArea.AreaKind.Navigation;
                marker.label = area.Label ?? "";
                marker.areaType = area.AreaType;
                marker.linkedEntityIds = area.EntityIds.ToArray();
                marker.notes = area.Reason ?? "";
            }
            foreach (CoverZone zone in data.CoverZones)
            {
                EnvGenGameplayArea marker = Area(root, gameplay, zone.Id, zone.Polygon, terrain);
                marker.areaKind = EnvGenGameplayArea.AreaKind.Cover;
                marker.label = zone.Label ?? "";
                marker.movement = zone.Movement;
                marker.projectileCover = zone.ProjectileCover;
                marker.vision = zone.Vision;
                marker.linkedEntityIds = zone.LinkedEntityIds.ToArray();
                marker.notes = zone.Notes ?? "";
            }
            foreach (CombatZone zone in data.CombatZones)
            {
                EnvGenGameplayArea marker = Area(root, gameplay, zone.Id, zone.Polygon, terrain);
                marker.areaKind = EnvGenGameplayArea.AreaKind.Combat;
                marker.label = zone.Label ?? "";
                marker.intensity = zone.Intensity;
                marker.engagementRange = zone.EngagementRange;
                marker.notes = zone.Notes ?? "";
            }
            foreach (SpawnClearance spawn in data.SpawnClearances)
            {
                GameObject go = Child(gameplay, spawn.Id);
                float x = (float)spawn.Position[0];
                float z = (float)spawn.Position[1];
                go.transform.localPosition = new Vector3(x, GroundY(root, terrain, x, z), z);
                EnvGenGameplayArea marker = go.AddComponent<EnvGenGameplayArea>();
                marker.areaId = spawn.Id;
                marker.label = spawn.Label ?? "";
                marker.areaKind = EnvGenGameplayArea.AreaKind.Spawn;
                marker.radius = (float)spawn.RadiusM;
                marker.intensity = spawn.Role;
            }
            foreach (LineOfSight sight in data.LineOfSight)
            {
                GameObject go = Child(gameplay, sight.Id);
                EnvGenSightLine line = go.AddComponent<EnvGenSightLine>();
                line.sightLineId = sight.Id;
                line.label = sight.Label ?? "";
                line.from = ManifestSceneImporter.ToVector3(sight.FromPosition);
                line.to = ManifestSceneImporter.ToVector3(sight.ToPosition);
                line.expected = sight.Expected;
                line.notes = sight.Notes ?? "";
            }
        }

        private static GameObject Child(Transform parent, string name)
        {
            var go = new GameObject(name);
            Undo.RegisterCreatedObjectUndo(go, "Create annotation");
            go.transform.SetParent(parent, false);
            return go;
        }

        /// <summary>An area object at the polygon's centre with its outline draped on the terrain.</summary>
        private static EnvGenGameplayArea Area(Transform root, Transform parent, string id, double[][] polygon, Terrain terrain)
        {
            GameObject go = Child(parent, id);
            EnvGenGameplayArea marker = go.AddComponent<EnvGenGameplayArea>();
            marker.areaId = id;
            if (polygon == null || polygon.Length == 0)
            {
                return marker;
            }
            float cx = (float)polygon.Average(p => p[0]);
            float cz = (float)polygon.Average(p => p[1]);
            var centre = new Vector3(cx, GroundY(root, terrain, cx, cz), cz);
            go.transform.localPosition = centre;
            marker.outline = polygon
                .Select(p => new Vector3((float)p[0], GroundY(root, terrain, (float)p[0], (float)p[1]), (float)p[1]) - centre)
                .ToArray();
            return marker;
        }

        /// <summary>Terrain height at location (x, z), in the root's local space (0 without terrain).</summary>
        private static float GroundY(Transform root, Terrain terrain, float x, float z)
        {
            if (terrain == null)
            {
                return 0f;
            }
            Vector3 world = root.TransformPoint(new Vector3(x, 0f, z));
            float height = terrain.SampleHeight(world) + terrain.transform.position.y;
            return root.InverseTransformPoint(new Vector3(world.x, height, world.z)).y;
        }
    }
}
