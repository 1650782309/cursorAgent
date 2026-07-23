using System;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 语音合成（TTS）配置。默认走 OpenAI 兼容的 /audio/speech 接口。
    /// 千问(DashScope)、OpenAI、部分本地服务均可用同一形态；不同服务的
    /// voice / model 取值不同，按各自文档填写。
    /// </summary>
    [Serializable]
    public class TTSConfig
    {
        public bool enabled = false;
        public string baseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1";
        public string apiKey = "";
        public string model = "qwen-tts";
        public string voice = "Chelsie";

        /// <summary>输出音频格式，运行时解码用。桌面端 wav 最稳，mp3 也可。</summary>
        public string format = "wav";
    }
}
