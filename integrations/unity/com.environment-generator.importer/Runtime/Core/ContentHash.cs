// Recomputes a manifest's contentHash exactly as the Python generator does
// (environment_generator.core.hashing.fingerprint):
//
//   sha256( UTF-8( json.dumps(canonicalize(manifest without "contentHash"),
//                             sort_keys=True, separators=(",", ":"),
//                             ensure_ascii=False) ) )
//
// canonicalize() rounds every float to 4 decimals with Python's round()
// (correctly rounded from the exact binary value, ties to even) and turns
// -0.0 into 0.0; json.dumps writes floats with Python's repr().

using System;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json.Linq;

namespace EnvGen.Importer.Core
{
    public static class ContentHash
    {
        public const string FieldName = "contentHash";
        public const string Prefix = "sha256:";

        /// <summary><c>sha256:&lt;hex&gt;</c> of the manifest without its <c>contentHash</c> field.</summary>
        public static string Compute(JObject manifest)
        {
            if (manifest == null)
            {
                throw new ArgumentNullException(nameof(manifest));
            }
            string canonical = CanonicalJson.Serialize(manifest, FieldName);
            using (SHA256 sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(new UTF8Encoding(false).GetBytes(canonical));
                var hex = new StringBuilder(Prefix.Length + digest.Length * 2);
                hex.Append(Prefix);
                foreach (byte b in digest)
                {
                    hex.Append(b.ToString("x2", CultureInfo.InvariantCulture));
                }
                return hex.ToString();
            }
        }
    }

    /// <summary>Python-compatible canonical JSON (see <see cref="ContentHash"/>).</summary>
    public static class CanonicalJson
    {
        public const int FloatDecimals = 4;

        /// <param name="skipTopLevelKey">Key of the root object to leave out (or null).</param>
        public static string Serialize(JToken token, string skipTopLevelKey = null)
        {
            var builder = new StringBuilder();
            Write(token, builder, skipTopLevelKey);
            return builder.ToString();
        }

        private static void Write(JToken token, StringBuilder builder, string skipKey)
        {
            switch (token.Type)
            {
                case JTokenType.Object:
                    builder.Append('{');
                    bool first = true;
                    foreach (JProperty property in ((JObject)token).Properties()
                                 .Where(p => skipKey == null || p.Name != skipKey)
                                 .OrderBy(p => p.Name, StringComparer.Ordinal))
                    {
                        if (!first)
                        {
                            builder.Append(',');
                        }
                        first = false;
                        WriteString(property.Name, builder);
                        builder.Append(':');
                        Write(property.Value, builder, null);
                    }
                    builder.Append('}');
                    break;
                case JTokenType.Array:
                    builder.Append('[');
                    bool firstItem = true;
                    foreach (JToken item in (JArray)token)
                    {
                        if (!firstItem)
                        {
                            builder.Append(',');
                        }
                        firstItem = false;
                        Write(item, builder, null);
                    }
                    builder.Append(']');
                    break;
                case JTokenType.Integer:
                    object value = ((JValue)token).Value;
                    builder.Append(value is BigInteger big
                        ? big.ToString(CultureInfo.InvariantCulture)
                        : Convert.ToString(value, CultureInfo.InvariantCulture));
                    break;
                case JTokenType.Float:
                    double rounded = PythonFloat.Round(token.Value<double>(), FloatDecimals);
                    builder.Append(PythonFloat.Repr(rounded == 0.0 ? 0.0 : rounded));
                    break;
                case JTokenType.String:
                    WriteString(token.Value<string>(), builder);
                    break;
                case JTokenType.Boolean:
                    builder.Append(token.Value<bool>() ? "true" : "false");
                    break;
                case JTokenType.Null:
                    builder.Append("null");
                    break;
                default:
                    throw new NotSupportedException($"Unsupported JSON token in a manifest: {token.Type}");
            }
        }

        /// <summary>Same escaping as Python's json.dumps(ensure_ascii=False).</summary>
        private static void WriteString(string text, StringBuilder builder)
        {
            builder.Append('"');
            foreach (char c in text)
            {
                switch (c)
                {
                    case '"': builder.Append("\\\""); break;
                    case '\\': builder.Append("\\\\"); break;
                    case '\n': builder.Append("\\n"); break;
                    case '\r': builder.Append("\\r"); break;
                    case '\t': builder.Append("\\t"); break;
                    case '\b': builder.Append("\\b"); break;
                    case '\f': builder.Append("\\f"); break;
                    default:
                        if (c < 0x20)
                        {
                            builder.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            builder.Append(c);
                        }
                        break;
                }
            }
            builder.Append('"');
        }
    }

    /// <summary>Python float semantics needed for hashing: <c>round(x, n)</c> and <c>repr(x)</c>.</summary>
    public static class PythonFloat
    {
        /// <summary>
        /// Python's <c>round(value, decimals)</c>: the exact binary value rounded to
        /// <paramref name="decimals"/> places, ties to even, converted back to the nearest double.
        /// </summary>
        public static double Round(double value, int decimals)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
            {
                throw new ArgumentException("non-finite floats cannot be serialised", nameof(value));
            }
            if (value == 0.0)
            {
                return value;
            }
            long bits = BitConverter.DoubleToInt64Bits(value);
            bool negative = bits < 0;
            int exponentBits = (int)((bits >> 52) & 0x7FF);
            long fraction = bits & 0xFFFFFFFFFFFFFL;
            BigInteger mantissa;
            int exponent;
            if (exponentBits == 0)
            {
                mantissa = fraction;
                exponent = -1074;
            }
            else
            {
                mantissa = fraction | (1L << 52);
                exponent = exponentBits - 1075;
            }

            // |value| = mantissa * 2^exponent exactly; scale by 10^decimals and round to an integer.
            BigInteger numerator = mantissa * BigInteger.Pow(10, decimals);
            BigInteger denominator = BigInteger.One;
            if (exponent >= 0)
            {
                numerator <<= exponent;
            }
            else
            {
                denominator <<= -exponent;
            }
            BigInteger quotient = BigInteger.DivRem(numerator, denominator, out BigInteger remainder);
            int comparison = (remainder * 2).CompareTo(denominator);
            if (comparison > 0 || (comparison == 0 && !quotient.IsEven))
            {
                quotient += 1;
            }

            string digits = quotient.ToString(CultureInfo.InvariantCulture);
            string text;
            if (decimals == 0)
            {
                text = digits;
            }
            else
            {
                digits = digits.PadLeft(decimals + 1, '0');
                text = digits.Substring(0, digits.Length - decimals) + "." + digits.Substring(digits.Length - decimals);
            }
            double result = double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture);
            return negative ? -result : result;
        }

        /// <summary>Python's <c>repr(value)</c> for a finite float (shortest round-trip digits).</summary>
        public static string Repr(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value))
            {
                throw new ArgumentException("non-finite floats cannot be serialised", nameof(value));
            }
            if (value == 0.0)
            {
                return BitConverter.DoubleToInt64Bits(value) < 0 ? "-0.0" : "0.0";
            }
            ShortestDigits(Math.Abs(value), out string digits, out int point);
            string body;
            if (point <= -4 || point > 16)
            {
                int exponent = point - 1;
                body = digits.Substring(0, 1)
                       + (digits.Length > 1 ? "." + digits.Substring(1) : "")
                       + "e" + (exponent < 0 ? "-" : "+")
                       + Math.Abs(exponent).ToString("00", CultureInfo.InvariantCulture);
            }
            else if (point <= 0)
            {
                body = "0." + new string('0', -point) + digits;
            }
            else if (point >= digits.Length)
            {
                body = digits + new string('0', point - digits.Length) + ".0";
            }
            else
            {
                body = digits.Substring(0, point) + "." + digits.Substring(point);
            }
            return value < 0 ? "-" + body : body;
        }

        /// <summary>
        /// Shortest significant digits that round-trip, and the decimal point position
        /// (value = 0.digits * 10^point).
        /// </summary>
        private static void ShortestDigits(double value, out string digits, out int point)
        {
            for (int precision = 1; precision <= 17; precision++)
            {
                string text = value.ToString("E" + (precision - 1), CultureInfo.InvariantCulture);
                if (double.Parse(text, NumberStyles.Float, CultureInfo.InvariantCulture) != value)
                {
                    continue;
                }
                int e = text.IndexOf('E');
                digits = text.Substring(0, e).Replace(".", "").TrimEnd('0');
                if (digits.Length == 0)
                {
                    digits = "0";
                }
                point = int.Parse(text.Substring(e + 1), NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture) + 1;
                return;
            }
            throw new InvalidOperationException("no round-trip representation found");
        }
    }
}
