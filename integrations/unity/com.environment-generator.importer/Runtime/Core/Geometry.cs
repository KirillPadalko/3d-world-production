// Engine-free geometry for the importer: heightfield resampling for Unity
// terrain, road ribbons, water polygons, junction discs and sagging cables.
//
// All coordinates are in the location frame (= Unity frame): X east, Y up,
// Z north. Triangles are wound so that Cross(b - a, c - a) points up (+Y),
// which is Unity's front-face orientation for a mesh seen from above.

using System;
using System.Collections.Generic;

namespace EnvGen.Importer.Core
{
    public struct Vec3
    {
        public double X;
        public double Y;
        public double Z;

        public Vec3(double x, double y, double z)
        {
            X = x;
            Y = y;
            Z = z;
        }

        public static Vec3 FromArray(double[] values) => new Vec3(values[0], values[1], values[2]);

        public static Vec3 operator +(Vec3 a, Vec3 b) => new Vec3(a.X + b.X, a.Y + b.Y, a.Z + b.Z);

        public static Vec3 operator -(Vec3 a, Vec3 b) => new Vec3(a.X - b.X, a.Y - b.Y, a.Z - b.Z);

        public static Vec3 operator *(Vec3 a, double s) => new Vec3(a.X * s, a.Y * s, a.Z * s);

        public static Vec3 Cross(Vec3 a, Vec3 b) =>
            new Vec3(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);

        public double HorizontalLength => Math.Sqrt(X * X + Z * Z);

        public override string ToString() => $"({X}, {Y}, {Z})";
    }

    /// <summary>Vertices, triangle indices and UVs ready to copy into a Unity Mesh.</summary>
    public sealed class MeshData
    {
        public List<Vec3> Vertices { get; } = new List<Vec3>();
        public List<int> Triangles { get; } = new List<int>();
        public List<double[]> Uvs { get; } = new List<double[]>();

        /// <summary>Shift every vertex so that <paramref name="origin"/> becomes (0, 0, 0).</summary>
        public MeshData RelativeTo(Vec3 origin)
        {
            var result = new MeshData();
            foreach (Vec3 v in Vertices)
            {
                result.Vertices.Add(v - origin);
            }
            result.Triangles.AddRange(Triangles);
            result.Uvs.AddRange(Uvs);
            return result;
        }
    }

    // ------------------------------------------------------------------ terrain

    public sealed class HeightfieldSamples
    {
        /// <summary>Unity heightmap resolution (2^n + 1).</summary>
        public int Resolution { get; set; }

        /// <summary><c>[z, x]</c> heights normalised to 0..1 (Unity's TerrainData.SetHeights layout).</summary>
        public float[,] Normalized { get; set; }

        public double SizeX { get; set; }
        public double SizeZ { get; set; }
        public double MinElevation { get; set; }

        /// <summary>Vertical extent of the terrain (TerrainData.size.y); at least 0.01 m.</summary>
        public double HeightRange { get; set; }
    }

    public static class HeightfieldResampler
    {
        public const int MinResolution = 33;
        public const int MaxResolution = 4097;

        /// <summary>Smallest 2^n + 1 resolution covering the grid, clamped to [33, maxResolution].</summary>
        public static int ChooseResolution(int columns, int rows, int maxResolution = 1025)
        {
            maxResolution = Math.Min(Math.Max(maxResolution, MinResolution), MaxResolution);
            int needed = Math.Max(columns, rows);
            int resolution = MinResolution;
            while (resolution < needed && resolution < maxResolution)
            {
                resolution = (resolution - 1) * 2 + 1;
            }
            return Math.Min(resolution, maxResolution);
        }

        /// <summary>Bilinear resample of the manifest grid to a square Unity heightmap.</summary>
        public static HeightfieldSamples Resample(TerrainGrid grid, int resolution)
        {
            if (resolution < 2)
            {
                throw new ArgumentOutOfRangeException(nameof(resolution));
            }
            double min = grid.MinElevationM;
            double range = Math.Max(grid.MaxElevationM - min, 0.01);
            var heights = new float[resolution, resolution];
            for (int j = 0; j < resolution; j++)
            {
                double gz = (double)j / (resolution - 1) * (grid.Rows - 1);
                for (int i = 0; i < resolution; i++)
                {
                    double gx = (double)i / (resolution - 1) * (grid.Columns - 1);
                    double h = Bilinear(grid.Heights, grid.Columns, grid.Rows, gx, gz);
                    heights[j, i] = (float)Math.Min(1.0, Math.Max(0.0, (h - min) / range));
                }
            }
            return new HeightfieldSamples
            {
                Resolution = resolution,
                Normalized = heights,
                SizeX = grid.SizeX,
                SizeZ = grid.SizeZ,
                MinElevation = min,
                HeightRange = range,
            };
        }

        /// <summary>Elevation at grid coordinates (fractional column, fractional row).</summary>
        public static double Bilinear(double[][] heights, int columns, int rows, double gx, double gz)
        {
            gx = Math.Min(Math.Max(gx, 0.0), columns - 1);
            gz = Math.Min(Math.Max(gz, 0.0), rows - 1);
            int i0 = Math.Min((int)Math.Floor(gx), columns - 2);
            int j0 = Math.Min((int)Math.Floor(gz), rows - 2);
            double tx = gx - i0;
            double tz = gz - j0;
            double h00 = heights[j0][i0];
            double h10 = heights[j0][i0 + 1];
            double h01 = heights[j0 + 1][i0];
            double h11 = heights[j0 + 1][i0 + 1];
            double south = h00 + (h10 - h00) * tx;
            double north = h01 + (h11 - h01) * tx;
            return south + (north - south) * tz;
        }
    }

    // ------------------------------------------------------------------ meshes

    public static class RibbonMeshBuilder
    {
        /// <summary>
        /// A flat strip of <paramref name="width"/> centred on a polyline (roads), lifted by
        /// <paramref name="lift"/> metres. UV u runs across (0 = left, 1 = right), v along the
        /// road in units of its width.
        /// </summary>
        public static MeshData Build(IReadOnlyList<Vec3> points, double width, double lift)
        {
            var clean = new List<Vec3>();
            foreach (Vec3 p in points)
            {
                if (clean.Count == 0 || (p - clean[clean.Count - 1]).HorizontalLength > 1e-6)
                {
                    clean.Add(p);
                }
            }
            if (clean.Count < 2)
            {
                throw new ArgumentException("a ribbon needs two distinct points", nameof(points));
            }
            if (width <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(width));
            }
            var mesh = new MeshData();
            double half = width / 2.0;
            double along = 0.0;
            for (int i = 0; i < clean.Count; i++)
            {
                Vec3 before = clean[Math.Max(i - 1, 0)];
                Vec3 after = clean[Math.Min(i + 1, clean.Count - 1)];
                Vec3 direction = after - before;
                double length = direction.HorizontalLength;
                // Facing along (dx, dz), the right-hand side is (dz, -dx) in this left-handed frame.
                var right = new Vec3(direction.Z / length, 0.0, -direction.X / length);
                if (i > 0)
                {
                    along += (clean[i] - clean[i - 1]).HorizontalLength;
                }
                Vec3 centre = clean[i] + new Vec3(0.0, lift, 0.0);
                mesh.Vertices.Add(centre - right * half);
                mesh.Vertices.Add(centre + right * half);
                mesh.Uvs.Add(new[] { 0.0, along / width });
                mesh.Uvs.Add(new[] { 1.0, along / width });
            }
            for (int i = 0; i < clean.Count - 1; i++)
            {
                int l0 = 2 * i, r0 = 2 * i + 1, l1 = 2 * i + 2, r1 = 2 * i + 3;
                mesh.Triangles.AddRange(new[] { l0, l1, r0, r0, l1, r1 });
            }
            return mesh;
        }
    }

    public static class PolygonTriangulator
    {
        /// <summary>
        /// Ear clipping of a simple polygon given as <c>[x, z]</c> points (either orientation).
        /// Returns triangle indices into <paramref name="polygon"/>, wound to face up.
        /// </summary>
        public static List<int> Triangulate(IReadOnlyList<double[]> polygon)
        {
            int n = polygon.Count;
            if (n < 3)
            {
                throw new ArgumentException("a polygon needs three points", nameof(polygon));
            }
            var indices = new List<int>();
            for (int i = 0; i < n; i++)
            {
                indices.Add(i);
            }
            if (SignedArea(polygon) < 0)
            {
                indices.Reverse(); // work counter-clockwise in the (x, z) plane
            }
            var triangles = new List<int>();
            int guard = 0;
            while (indices.Count > 3 && guard++ < n * n)
            {
                bool clipped = false;
                for (int k = 0; k < indices.Count; k++)
                {
                    int a = indices[(k + indices.Count - 1) % indices.Count];
                    int b = indices[k];
                    int c = indices[(k + 1) % indices.Count];
                    if (Cross(polygon[a], polygon[b], polygon[c]) <= 1e-12)
                    {
                        continue; // reflex or degenerate corner
                    }
                    bool contains = false;
                    foreach (int other in indices)
                    {
                        if (other != a && other != b && other != c && InTriangle(polygon[other], polygon[a], polygon[b], polygon[c]))
                        {
                            contains = true;
                            break;
                        }
                    }
                    if (contains)
                    {
                        continue;
                    }
                    // Counter-clockwise in (x, z) faces down in Unity; emit (a, c, b) to face up.
                    triangles.AddRange(new[] { a, c, b });
                    indices.RemoveAt(k);
                    clipped = true;
                    break;
                }
                if (!clipped)
                {
                    throw new ArgumentException("the polygon is not simple", nameof(polygon));
                }
            }
            triangles.AddRange(new[] { indices[0], indices[2], indices[1] });
            return triangles;
        }

        /// <summary>Shoelace area in the (x, z) plane; positive = counter-clockwise.</summary>
        public static double SignedArea(IReadOnlyList<double[]> polygon)
        {
            double sum = 0.0;
            for (int i = 0; i < polygon.Count; i++)
            {
                double[] p = polygon[i];
                double[] q = polygon[(i + 1) % polygon.Count];
                sum += p[0] * q[1] - q[0] * p[1];
            }
            return sum / 2.0;
        }

        private static double Cross(double[] a, double[] b, double[] c) =>
            (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);

        private static bool InTriangle(double[] p, double[] a, double[] b, double[] c)
        {
            double d1 = Side(p, a, b);
            double d2 = Side(p, b, c);
            double d3 = Side(p, c, a);
            bool negative = d1 < 0 || d2 < 0 || d3 < 0;
            bool positive = d1 > 0 || d2 > 0 || d3 > 0;
            return !(negative && positive);
        }

        private static double Side(double[] p, double[] a, double[] b) =>
            (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]);
    }

    public static class SurfaceMeshBuilder
    {
        /// <summary>Flat polygon (water) at the mean height of its points plus <paramref name="lift"/>.</summary>
        public static MeshData Polygon(IReadOnlyList<double[]> points3, double lift)
        {
            var ring = new List<double[]>();
            double sumY = 0.0;
            foreach (double[] p in points3)
            {
                ring.Add(new[] { p[0], p[2] });
                sumY += p[1];
            }
            double y = sumY / points3.Count + lift;
            var mesh = new MeshData();
            foreach (double[] p in ring)
            {
                mesh.Vertices.Add(new Vec3(p[0], y, p[1]));
                mesh.Uvs.Add(new[] { p[0], p[1] });
            }
            mesh.Triangles.AddRange(PolygonTriangulator.Triangulate(ring));
            return mesh;
        }

        /// <summary>Flat disc (road junction) centred on <paramref name="centre"/>.</summary>
        public static MeshData Disc(Vec3 centre, double radius, int segments, double lift)
        {
            if (radius <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(radius));
            }
            segments = Math.Max(segments, 3);
            var mesh = new MeshData();
            mesh.Vertices.Add(centre + new Vec3(0.0, lift, 0.0));
            mesh.Uvs.Add(new[] { 0.5, 0.5 });
            for (int k = 0; k < segments; k++)
            {
                double angle = 2.0 * Math.PI * k / segments;
                double x = Math.Cos(angle);
                double z = Math.Sin(angle);
                mesh.Vertices.Add(centre + new Vec3(x * radius, lift, z * radius));
                mesh.Uvs.Add(new[] { 0.5 + x / 2.0, 0.5 + z / 2.0 });
            }
            for (int k = 0; k < segments; k++)
            {
                int current = 1 + k;
                int next = 1 + (k + 1) % segments;
                // Vertices go counter-clockwise in (x, z); (centre, next, current) faces up.
                mesh.Triangles.AddRange(new[] { 0, next, current });
            }
            return mesh;
        }
    }

    public static class CableSag
    {
        /// <summary>
        /// Points of a cable hanging between consecutive supports: each span is a parabola that
        /// drops by <paramref name="sagM"/> at its middle. Support points are kept exactly.
        /// </summary>
        public static List<Vec3> Sample(IReadOnlyList<Vec3> supports, double sagM, int samplesPerSpan)
        {
            var result = new List<Vec3>();
            if (supports.Count == 0)
            {
                return result;
            }
            samplesPerSpan = Math.Max(samplesPerSpan, 1);
            result.Add(supports[0]);
            for (int s = 0; s < supports.Count - 1; s++)
            {
                Vec3 a = supports[s];
                Vec3 b = supports[s + 1];
                for (int k = 1; k <= samplesPerSpan; k++)
                {
                    double t = (double)k / samplesPerSpan;
                    Vec3 point = a + (b - a) * t;
                    if (k < samplesPerSpan)
                    {
                        point.Y -= 4.0 * sagM * t * (1.0 - t);
                    }
                    result.Add(k == samplesPerSpan ? b : point);
                }
            }
            return result;
        }
    }
}
