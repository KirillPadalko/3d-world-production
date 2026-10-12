using UnityEngine;

namespace EnvGen.Importer
{
    /// <summary>
    /// A gameplay annotation area from the LocationBlueprint: navigation area, cover
    /// zone, combat zone or spawn clearance. Movement, projectile cover and vision are
    /// kept separate (e.g. a board fence blocks movement and sight but not bullets).
    /// </summary>
    [AddComponentMenu("Environment Generator/Gameplay Area")]
    public sealed class EnvGenGameplayArea : MonoBehaviour
    {
        public enum AreaKind
        {
            Navigation,
            Cover,
            Combat,
            Spawn,
        }

        public string areaId = "";
        public string label = "";
        public AreaKind areaKind;

        [Tooltip("Outline in local coordinates, projected onto the terrain at import time.")]
        public Vector3[] outline = new Vector3[0];

        [Tooltip("Spawn clearances: radius in metres.")]
        public float radius;

        [Tooltip("Navigation: walkable or blocked.")]
        public string areaType = "";

        [Tooltip("Cover: none, slow or block.")]
        public string movement = "";

        [Tooltip("Cover: none, partial or full.")]
        public string projectileCover = "";

        [Tooltip("Cover: visual occlusion none, partial or full.")]
        public string vision = "";

        [Tooltip("Combat: low, medium or high; spawn: role.")]
        public string intensity = "";
        public string engagementRange = "";
        public string[] linkedEntityIds = new string[0];
        public string notes = "";

        private Color GizmoColor()
        {
            switch (areaKind)
            {
                case AreaKind.Navigation:
                    return areaType == "blocked" ? new Color(0.9f, 0.1f, 0.1f) : new Color(0.2f, 0.8f, 0.3f);
                case AreaKind.Cover:
                    return new Color(0.2f, 0.5f, 1f);
                case AreaKind.Combat:
                    return new Color(1f, 0.4f, 0.1f);
                default:
                    return new Color(0.8f, 0.2f, 0.9f);
            }
        }

        private void OnDrawGizmos()
        {
            Gizmos.color = GizmoColor();
            Matrix4x4 previous = Gizmos.matrix;
            Gizmos.matrix = transform.localToWorldMatrix;
            for (int i = 0; i < outline.Length; i++)
            {
                Vector3 a = outline[i] + Vector3.up * 0.2f;
                Vector3 b = outline[(i + 1) % outline.Length] + Vector3.up * 0.2f;
                Gizmos.DrawLine(a, b);
            }
            if (radius > 0f)
            {
                Gizmos.DrawWireSphere(Vector3.zero, radius);
            }
            Gizmos.matrix = previous;
        }
    }
}
