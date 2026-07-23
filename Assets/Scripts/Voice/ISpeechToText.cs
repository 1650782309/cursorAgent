using System.Threading;
using System.Threading.Tasks;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 语音识别统一接口。输入 WAV 音频字节，输出识别文本。
    /// 与具体服务解耦，便于将来切换本地 ASR（whisper.cpp / sherpa-onnx 等）。
    /// </summary>
    public interface ISpeechToText
    {
        Task<string> TranscribeAsync(byte[] wavAudio, CancellationToken cancellationToken);
    }
}
