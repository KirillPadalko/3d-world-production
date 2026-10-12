using System;
using UnityEngine;

namespace EnvGen.Importer
{
    /// <summary>
    /// A generated entity. The GameObject carries the manifest transform exactly;
    /// its child named "visual" is rebuilt on every import, other children and
    /// components you add are kept.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Environment Generator/Entity")]
    public sealed class EnvGenEntity : MonoBehaviour
    {
        [Serializable]
        public struct Parameter
        {
            public string key;

            [Tooltip("JSON value as text (strings without quotes).")]
            public string value;
        }

        [Tooltip("Stable manifest ID, e.g. building.b-house-02.")]
        public string entityId = "";
        public string category = "";
        public string kind = "";
        public string archetypeId = "";
        public string assetRef = "";
        public int variant;

        [Tooltip("The generator itself had no archetype (placeholder.* archetype).")]
        public bool generatorPlaceholder;

        [Tooltip("How the visual was chosen: archetype, kind, placeholder or a generated mesh.")]
        public string binding = "";

        [Tooltip("World size: x = width, y = height, z = depth (metres).")]
        public Vector3 dimensions;

        public string generator = "";
        public string implementation = "";
        public string rule = "";
        public string sourceFeature = "";

        [Tooltip("Overrides that shaped this entity (<overridesId>#entityOperations[i] ...).")]
        public string[] overrides = new string[0];
        public string[] tags = new string[0];
        public Parameter[] parameters = new Parameter[0];

        public bool TryGetParameter(string key, out string value)
        {
            foreach (Parameter parameter in parameters)
            {
                if (parameter.key == key)
                {
                    value = parameter.value;
                    return true;
                }
            }
            value = null;
            return false;
        }
    }
}
