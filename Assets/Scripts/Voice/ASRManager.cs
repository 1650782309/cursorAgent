using System.IO;
using UnityEngine;
using Newtonsoft.Json;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 从 StreamingAssets/Config/asr_config.json 加载 ASR 配置并创建供应商。
    /// 支持 asr_config.local.json 覆盖（真实 key，已在 .gitignore 忽略）。
    /// </summary>
    public static class ASRManager
    {
        private const string Dir = "Config";
        private const string FileName = "asr_config.json";
        private const string LocalFileName = "asr_config.local.json";

        public static ASRConfig LoadConfig()
        {
            string baseDir = Path.Combine(Application.streamingAssetsPath, Dir);
            string localPath = Path.Combine(baseDir, LocalFileName);
            string path = File.Exists(localPath) ? localPath : Path.Combine(baseDir, FileName);

            if (!File.Exists(path)) return new ASRConfig();
            try
            {
                return JsonConvert.DeserializeObject<ASRConfig>(File.ReadAllText(path))
                       ?? new ASRConfig();
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[ASRManager] 解析 asr_config.json 失败: {e.Message}");
                return new ASRConfig();
            }
        }

        public static ISpeechToText CreateProvider(ASRConfig config)
        {
            return new OpenAICompatibleSTT(config);
        }
    }
}
