using System.IO;
using UnityEngine;
using Newtonsoft.Json;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 从 StreamingAssets/Config/tts_config.json 加载 TTS 配置并创建供应商。
    /// 支持 tts_config.local.json 覆盖（存放真实 key，已在 .gitignore 忽略）。
    /// </summary>
    public static class TTSManager
    {
        private const string Dir = "Config";
        private const string FileName = "tts_config.json";
        private const string LocalFileName = "tts_config.local.json";

        public static TTSConfig LoadConfig()
        {
            string baseDir = Path.Combine(Application.streamingAssetsPath, Dir);
            string localPath = Path.Combine(baseDir, LocalFileName);
            string path = File.Exists(localPath) ? localPath : Path.Combine(baseDir, FileName);

            if (!File.Exists(path)) return new TTSConfig();
            try
            {
                return JsonConvert.DeserializeObject<TTSConfig>(File.ReadAllText(path))
                       ?? new TTSConfig();
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[TTSManager] 解析 tts_config.json 失败: {e.Message}");
                return new TTSConfig();
            }
        }

        public static ITextToSpeech CreateProvider(TTSConfig config)
        {
            return new OpenAICompatibleTTS(config);
        }
    }
}
