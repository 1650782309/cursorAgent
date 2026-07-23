using System.IO;
using UnityEngine;
using Newtonsoft.Json;
using DesktopCompanion.Brain;

namespace DesktopCompanion.App
{
    /// <summary>从 StreamingAssets/Config/persona.json 加载人设，缺失时用默认值。</summary>
    public static class PersonaLoader
    {
        public static PersonaConfig Load()
        {
            string path = Path.Combine(Application.streamingAssetsPath, "Config", "persona.json");
            if (!File.Exists(path)) return new PersonaConfig();
            try
            {
                return JsonConvert.DeserializeObject<PersonaConfig>(File.ReadAllText(path))
                       ?? new PersonaConfig();
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[PersonaLoader] 解析 persona.json 失败: {e.Message}");
                return new PersonaConfig();
            }
        }
    }
}
