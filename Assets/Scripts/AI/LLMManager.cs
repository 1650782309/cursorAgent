using System.IO;
using UnityEngine;
using Newtonsoft.Json;

namespace DesktopCompanion.AI
{
    /// <summary>
    /// 从 StreamingAssets/Config 加载模型配置并创建激活的供应商。
    /// 优先读取 model_config.local.json（本地私密配置，已在 .gitignore 中忽略），
    /// 不存在时回退到随仓库提交的 model_config.json 模板。
    /// </summary>
    public static class LLMManager
    {
        private const string Dir = "Config";
        private const string FileName = "model_config.json";
        private const string LocalFileName = "model_config.local.json";

        public static LLMConfigFile LoadConfig()
        {
            string baseDir = Path.Combine(Application.streamingAssetsPath, Dir);
            string localPath = Path.Combine(baseDir, LocalFileName);
            string path = File.Exists(localPath) ? localPath : Path.Combine(baseDir, FileName);

            if (!File.Exists(path))
            {
                Debug.LogWarning($"[LLMManager] 未找到配置 {path}，使用内置默认（DeepSeek，需填 apiKey）。");
                return DefaultConfig();
            }

            try
            {
                return JsonConvert.DeserializeObject<LLMConfigFile>(File.ReadAllText(path))
                       ?? DefaultConfig();
            }
            catch (System.Exception e)
            {
                Debug.LogError($"[LLMManager] 解析配置失败: {e.Message}");
                return DefaultConfig();
            }
        }

        public static ILLMProvider CreateProvider(LLMConfigFile config)
        {
            return new OpenAICompatibleProvider(config.GetActive());
        }

        private static LLMConfigFile DefaultConfig()
        {
            var cfg = new LLMConfigFile { active = "deepseek" };
            cfg.providers.Add(new LLMConfig
            {
                name = "deepseek",
                baseUrl = "https://api.deepseek.com/v1",
                model = "deepseek-chat"
            });
            return cfg;
        }
    }
}
