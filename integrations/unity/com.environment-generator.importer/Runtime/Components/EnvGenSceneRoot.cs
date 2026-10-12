using UnityEngine;

namespace EnvGen.Importer
{
    /// <summary>
    /// Root of an imported location. Everything under it is in the location frame
    /// (metres, +X east, +Y up, +Z north); move or rotate this object to place the
    /// location in a larger world.
    /// </summary>
    [DisallowMultipleComponent]
    [AddComponentMenu("Environment Generator/Scene Root")]
    public sealed class EnvGenSceneRoot : MonoBehaviour
    {
        public string locationId = "";
        public string locationName = "";
        public string recipeId = "";
        public string overridesId = "";
        public string registryId = "";
        public long seed;
        public string generatorName = "";
        public string generatorVersion = "";

        [Tooltip("Manifest file of the last import.")]
        public string manifestPath = "";

        [Tooltip("contentHash of the last imported manifest.")]
        public string contentHash = "";

        [Tooltip("True when the file was exactly what the generator wrote.")]
        public bool contentHashVerified;

        public string importedAtUtc = "";
    }
}
