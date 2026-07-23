using System.Collections.Generic;
using System.IO;
using UnityEngine;
using Newtonsoft.Json;
using DesktopCompanion.AI;

namespace DesktopCompanion.Brain
{
    /// <summary>
    /// 对话记忆：短期上下文（最近若干条原文）+ 长期摘要（旧对话被 LLM 压缩成 summary）。
    /// 落盘持久化为 JSON。
    ///
    /// 说明：这是无原生依赖的轻量实现。若需语义检索式长期记忆，
    /// 后续可接入 sqlite + 向量库，接口保持不变。
    /// </summary>
    public class MemoryStore
    {
        private class MemoryData
        {
            public string summary = "";
            public List<ChatMessage> history = new List<ChatMessage>();
        }

        private readonly int _hardCap;
        private readonly string _path;
        private readonly MemoryData _data = new MemoryData();

        /// <param name="hardCap">短期原文最多保留的条数（超出时最旧的被丢弃或转入摘要）。</param>
        public MemoryStore(int hardCap = 40)
        {
            _hardCap = hardCap;
            _path = Path.Combine(Application.persistentDataPath, "memory.json");
            Load();
        }

        public IReadOnlyList<ChatMessage> History => _data.history;

        public string Summary => _data.summary;

        public void SetSummary(string summary)
        {
            _data.summary = summary ?? "";
            Save();
        }

        public void Add(ChatMessage message)
        {
            _data.history.Add(message);
            if (_data.history.Count > _hardCap)
                _data.history.RemoveRange(0, _data.history.Count - _hardCap);
            Save();
        }

        /// <summary>
        /// 取出并移除最旧的 <paramref name="count"/> 条（供摘要器压缩）。
        /// count &lt;= 0 或超过现有数量时做安全裁剪。
        /// </summary>
        public List<ChatMessage> TakeOldest(int count)
        {
            count = Mathf.Clamp(count, 0, _data.history.Count);
            if (count == 0) return new List<ChatMessage>();

            var taken = _data.history.GetRange(0, count);
            _data.history.RemoveRange(0, count);
            Save();
            return taken;
        }

        public void Clear()
        {
            _data.history.Clear();
            _data.summary = "";
            Save();
        }

        private void Load()
        {
            if (!File.Exists(_path)) return;
            try
            {
                var loaded = JsonConvert.DeserializeObject<MemoryData>(File.ReadAllText(_path));
                if (loaded != null)
                {
                    _data.summary = loaded.summary ?? "";
                    _data.history = loaded.history ?? new List<ChatMessage>();
                }
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[MemoryStore] 加载记忆失败: {e.Message}");
            }
        }

        private void Save()
        {
            try
            {
                File.WriteAllText(_path, JsonConvert.SerializeObject(_data));
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[MemoryStore] 保存记忆失败: {e.Message}");
            }
        }
    }
}
