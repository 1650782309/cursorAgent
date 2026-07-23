using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using DesktopCompanion.AI;
using DesktopCompanion.Core;

namespace DesktopCompanion.Brain
{
    /// <summary>
    /// 对话编排（大脑核心）：拼装 system 人设 + 记忆 + 用户输入，调用模型流式生成，
    /// 解析情绪并通过事件通知身体（角色表情）与 UI（气泡）。
    ///
    /// 所有对外事件都保证在 Unity 主线程触发（通过 MainThreadDispatcher）。
    /// </summary>
    public class DialogueManager
    {
        private readonly ILLMProvider _provider;
        private readonly PersonaConfig _persona;
        private readonly MemoryStore _memory;
        private readonly MemorySummarizer _summarizer;

        // 短期原文超过该条数时，把最旧的一批折叠进长期摘要。
        private const int SummarizeThreshold = 24;
        private const int KeepRecent = 12;

        private CancellationTokenSource _cts;
        private bool _summarizing;

        /// <summary>流式增量：参数为「去掉情绪标签后的当前完整正文」。</summary>
        public event Action<string> OnPartialReply;

        /// <summary>解析出情绪时触发（通常在流式早期）。</summary>
        public event Action<Emotion> OnEmotion;

        /// <summary>回复结束：参数为最终情绪与正文。</summary>
        public event Action<Emotion, string> OnCompleteReply;

        public event Action<string> OnError;

        public DialogueManager(ILLMProvider provider, PersonaConfig persona, MemoryStore memory,
            MemorySummarizer summarizer = null)
        {
            _provider = provider;
            _persona = persona;
            _memory = memory;
            _summarizer = summarizer;
        }

        public void CancelOngoing()
        {
            _cts?.Cancel();
        }

        /// <summary>发送一条用户消息，异步流式获取回复。</summary>
        public async void Send(string userInput)
        {
            if (string.IsNullOrWhiteSpace(userInput)) return;

            _cts?.Cancel();
            _cts = new CancellationTokenSource();
            var token = _cts.Token;

            var messages = BuildMessages(userInput);

            string raw = "";
            bool emotionFired = false;

            try
            {
                await _provider.ChatStreamAsync(messages, delta =>
                {
                    // delta 可能来自后台线程 -> 切主线程处理。
                    MainThreadDispatcher.Instance.Enqueue(() =>
                    {
                        raw += delta;
                        var (emotion, clean) = EmotionParser.Parse(raw);

                        if (!emotionFired && ShouldFireEmotion(raw))
                        {
                            emotionFired = true;
                            OnEmotion?.Invoke(emotion);
                        }

                        OnPartialReply?.Invoke(clean);
                    });
                }, token);
            }
            catch (OperationCanceledException)
            {
                return; // 被新消息取消，静默返回。
            }
            catch (Exception e)
            {
                MainThreadDispatcher.Instance.Enqueue(() => OnError?.Invoke(e.Message));
                return;
            }

            MainThreadDispatcher.Instance.Enqueue(() =>
            {
                var (emotion, clean) = EmotionParser.Parse(raw);
                if (!emotionFired) OnEmotion?.Invoke(emotion);

                _memory.Add(new ChatMessage(Role.User, userInput));
                _memory.Add(new ChatMessage(Role.Assistant, raw));

                OnCompleteReply?.Invoke(emotion, clean);

                MaybeSummarize();
            });
        }

        // 当短期原文过长时，异步把最旧的一批折叠进长期摘要（不阻塞对话）。
        private void MaybeSummarize()
        {
            if (_summarizer == null || _summarizing) return;
            if (_memory.History.Count <= SummarizeThreshold) return;

            _summarizing = true;
            string existing = _memory.Summary;
            var older = _memory.TakeOldest(_memory.History.Count - KeepRecent);

            _ = SummarizeAsync(existing, older);
        }

        private async Task SummarizeAsync(string existing, List<ChatMessage> older)
        {
            try
            {
                string summary = await _summarizer.SummarizeAsync(existing, older);
                MainThreadDispatcher.Instance.Enqueue(() => _memory.SetSummary(summary));
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[DialogueManager] 记忆摘要失败: {e.Message}");
            }
            finally
            {
                _summarizing = false;
            }
        }

        private List<ChatMessage> BuildMessages(string userInput)
        {
            var list = new List<ChatMessage>
            {
                new ChatMessage(Role.System, _persona.BuildSystemPrompt())
            };

            if (!string.IsNullOrEmpty(_memory.Summary))
                list.Add(new ChatMessage(Role.System, "关于用户的长期记忆摘要：\n" + _memory.Summary));

            list.AddRange(_memory.History);
            list.Add(new ChatMessage(Role.User, userInput));
            return list;
        }

        // 一旦缓冲区里出现完整的情绪标签，或已经积累了一些正文（说明模型没给标签），
        // 就可以确定情绪，尽早驱动表情。
        private static bool ShouldFireEmotion(string raw)
        {
            if (raw.Contains("]")) return true;
            return raw.Length > 16;
        }
    }
}
