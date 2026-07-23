using System.Threading;
using System.Threading.Tasks;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 语音合成统一接口。返回音频字节（由 <see cref="TTSConfig.format"/> 决定格式）。
    /// 与具体服务商解耦，便于将来切换本地 TTS（GPT-SoVITS / VITS 等）。
    /// </summary>
    public interface ITextToSpeech
    {
        string Format { get; }

        Task<byte[]> SynthesizeAsync(string text, CancellationToken cancellationToken);
    }
}
