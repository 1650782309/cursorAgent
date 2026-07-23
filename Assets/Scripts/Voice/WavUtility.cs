using System.IO;
using System.Text;
using UnityEngine;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 把浮点 PCM 采样编码为 16-bit 单/多声道 WAV 字节，供上传给 ASR 服务。
    /// </summary>
    public static class WavUtility
    {
        public static byte[] FromSamples(float[] samples, int channels, int sampleRate)
        {
            if (samples == null || samples.Length == 0) return null;

            using var mem = new MemoryStream();
            using var w = new BinaryWriter(mem);

            int bitsPerSample = 16;
            int blockAlign = channels * bitsPerSample / 8;
            int byteRate = sampleRate * blockAlign;
            int dataSize = samples.Length * 2;

            // RIFF header
            w.Write(Encoding.ASCII.GetBytes("RIFF"));
            w.Write(36 + dataSize);
            w.Write(Encoding.ASCII.GetBytes("WAVE"));

            // fmt chunk
            w.Write(Encoding.ASCII.GetBytes("fmt "));
            w.Write(16);
            w.Write((short)1); // PCM
            w.Write((short)channels);
            w.Write(sampleRate);
            w.Write(byteRate);
            w.Write((short)blockAlign);
            w.Write((short)bitsPerSample);

            // data chunk
            w.Write(Encoding.ASCII.GetBytes("data"));
            w.Write(dataSize);
            for (int i = 0; i < samples.Length; i++)
            {
                short v = (short)Mathf.Clamp(samples[i] * 32767f, short.MinValue, short.MaxValue);
                w.Write(v);
            }

            w.Flush();
            return mem.ToArray();
        }
    }
}
