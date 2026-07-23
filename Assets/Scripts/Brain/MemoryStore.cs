using System.Collections.Generic;
using System.IO;
using UnityEngine;
using Newtonsoft.Json;
using DesktopCompanion.AI;

namespace DesktopCompanion.Brain
{
    /// <summary>
    /// 简单对话记忆：短期上下文（内存）+ 落盘持久化（JSON）。
    /// 说明：进阶的长期记忆（向量检索/摘要）建议后续接入 sqlite + 向量库，
    /// 这里先用轻量实现保证工程可跑、无原生依赖。
    /// </summary>
    public class MemoryStore
    {
        private readonly int _maxTurns;
        private readonly string _path;
        private readonly List<ChatMessage> _history = new List<ChatMessage>();

        public MemoryStore(int maxTurns = 20)
        {
            _maxTurns = maxTurns;
            _path = Path.Combine(Application.persistentDataPath, "memory.json");
            Load();
        }

        public IReadOnlyList<ChatMessage> History => _history;

        public void Add(ChatMessage message)
        {
            _history.Add(message);
            // 仅保留最近 N 轮（user+assistant 视为 2 条）。
            int max = _maxTurns * 2;
            if (_history.Count > max)
                _history.RemoveRange(0, _history.Count - max);
            Save();
        }

        public void Clear()
        {
            _history.Clear();
            Save();
        }

        private void Load()
        {
            if (!File.Exists(_path)) return;
            try
            {
                var loaded = JsonConvert.DeserializeObject<List<ChatMessage>>(File.ReadAllText(_path));
                if (loaded != null) _history.AddRange(loaded);
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
                File.WriteAllText(_path, JsonConvert.SerializeObject(_history));
            }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[MemoryStore] 保存记忆失败: {e.Message}");
            }
        }
    }
}
