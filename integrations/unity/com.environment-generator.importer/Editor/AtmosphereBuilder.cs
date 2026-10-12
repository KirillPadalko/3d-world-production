using EnvGen.Importer.Core;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace EnvGen.Importer.Editor
{
    /// <summary>
    /// Key light, ambient light and fog from the manifest atmosphere. Values are the
    /// generator's engine-neutral starting points (built-in pipeline scale); tune them
    /// for URP/HDRP exposure. RenderSettings changes are not part of the undo step.
    /// </summary>
    internal static class AtmosphereBuilder
    {
        public static void Apply(Transform root, AtmosphereSettings atmosphere)
        {
            Transform sunTransform = root.Find(ManifestSceneImporter.SunName);
            Light sun;
            if (sunTransform == null)
            {
                var go = new GameObject(ManifestSceneImporter.SunName);
                Undo.RegisterCreatedObjectUndo(go, "Create sun");
                go.transform.SetParent(root, false);
                sun = go.AddComponent<Light>();
            }
            else
            {
                sun = sunTransform.GetComponent<Light>();
                if (sun == null)
                {
                    sun = Undo.AddComponent<Light>(sunTransform.gameObject);
                }
                Undo.RecordObject(sun, "Update sun");
                Undo.RecordObject(sunTransform, "Update sun");
            }

            sun.type = LightType.Directional;
            Vector3 direction = ManifestSceneImporter.ToVector3(atmosphere.KeyLightDirection);
            if (direction.sqrMagnitude < 1e-8f)
            {
                direction = Vector3.down;
            }
            direction.Normalize();
            // keyLightDirection points from the light into the scene: the light's forward.
            Vector3 up = Mathf.Abs(direction.y) > 0.999f ? Vector3.forward : Vector3.up;
            sun.transform.localRotation = Quaternion.LookRotation(direction, up);
            sun.color = ManifestSceneImporter.ToColor(atmosphere.KeyLightColor);
            sun.intensity = (float)atmosphere.KeyLightIntensity;
            sun.shadows = LightShadows.Soft;

            RenderSettings.sun = sun;
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = ManifestSceneImporter.ToColor(atmosphere.AmbientColor) * (float)atmosphere.AmbientIntensity;
            RenderSettings.fog = atmosphere.FogDensity > 0.0;
            RenderSettings.fogMode = FogMode.Exponential;
            RenderSettings.fogDensity = (float)atmosphere.FogDensity;
            RenderSettings.fogColor = ManifestSceneImporter.ToColor(atmosphere.FogColor);
        }
    }
}
