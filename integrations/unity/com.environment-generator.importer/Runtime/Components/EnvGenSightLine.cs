using UnityEngine;

namespace EnvGen.Importer
{
    /// <summary>A designer line-of-sight expectation (clear, partial or blocked) to test against.</summary>
    [AddComponentMenu("Environment Generator/Sight Line")]
    public sealed class EnvGenSightLine : MonoBehaviour
    {
        public string sightLineId = "";
        public string label = "";

        [Tooltip("Local start and end points (eye heights included).")]
        public Vector3 from;
        public Vector3 to;

        [Tooltip("clear, partial or blocked.")]
        public string expected = "";
        public string notes = "";

        private void OnDrawGizmos()
        {
            Gizmos.color = expected == "blocked" ? Color.red : expected == "partial" ? Color.yellow : Color.green;
            Gizmos.DrawLine(transform.TransformPoint(from), transform.TransformPoint(to));
        }
    }
}
