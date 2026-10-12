using UnityEngine;

namespace EnvGen.Importer
{
    /// <summary>A LocationBlueprint landmark (orientation point, objective, ...).</summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Environment Generator/Landmark")]
    public sealed class EnvGenLandmark : MonoBehaviour
    {
        public string landmarkId = "";
        public string label = "";
        public string landmarkType = "";

        [Range(0f, 1f)] public float importance = 0.5f;

        [Tooltip("low, medium or high.")]
        public string visibility = "";

        [Tooltip("Distance from which it is recognisable; 0 = unknown.")]
        public float visibilityRadius;
        public string linkedEntityId = "";
        public string[] gameplayRoles = new string[0];

        private void OnDrawGizmos()
        {
            Gizmos.color = new Color(1f, 0.8f, 0.1f, 0.9f);
            Gizmos.DrawWireSphere(transform.position, 1.5f + 2f * importance);
            Gizmos.DrawLine(transform.position, transform.position + Vector3.up * 12f);
            if (visibilityRadius > 0f)
            {
                Gizmos.color = new Color(1f, 0.8f, 0.1f, 0.2f);
                Gizmos.DrawWireSphere(transform.position, visibilityRadius);
            }
        }
    }
}
