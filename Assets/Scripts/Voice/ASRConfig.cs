using System;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 语音识别（ASR）配置。默认走 OpenAI 兼容的 /audio/transcriptions 接口。
    /// - OpenAI Whisper：model = "whisper-1"
    /// - 本地：可指向自建 whisper.cpp / faster-whisper 的 OpenAI 兼容服务
    /// - 千问/DashScope 的 ASR 走法不同（paraformer），如用其原生接口需另写 Provider
    /// </summary>
    [Serializable]
    public class ASRConfig
    {
        public bool enabled = false;
        public string baseUrl = "https://api.openai.com/v1";
        public string apiKey = "";
        public string model = "whisper-1";

        /// <summary>识别语言（ISO-639-1，如 zh / en）。留空由服务自动检测。</summary>
        public string language = "zh";

        /// <summary>录音采样率。16000 对语音识别足够且体积小。</summary>
        public int sampleRate = 16000;

        /// <summary>按住说话的按键名（Unity KeyCode 名称）。</summary>
        public string pushToTalkKey = "LeftAlt";
    }
}
