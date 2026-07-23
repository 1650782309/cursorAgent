using System;
using System.Collections.Generic;

namespace DesktopCompanion.AI
{
    /// <summary>
    /// 单个模型供应商的配置。在线（千问/DeepSeek）与本地（Ollama）
    /// 统一走 OpenAI 兼容接口，差异仅在 baseUrl / apiKey / model。
    /// </summary>
    [Serializable]
    public class LLMConfig
    {
        public string name = "deepseek";
        public string baseUrl = "https://api.deepseek.com/v1";
        public string apiKey = "";
        public string model = "deepseek-chat";
        public float temperature = 0.8f;
        public bool stream = true;
    }

    /// <summary>模型配置文件：一组供应商 + 当前激活项。</summary>
    [Serializable]
    public class LLMConfigFile
    {
        public string active = "deepseek";
        public List<LLMConfig> providers = new List<LLMConfig>();

        public LLMConfig GetActive()
        {
            var p = providers.Find(x => x.name == active);
            return p ?? (providers.Count > 0 ? providers[0] : new LLMConfig());
        }
    }
}
