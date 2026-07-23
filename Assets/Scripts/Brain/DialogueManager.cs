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

        private CancellationTokenSource _cts;

        /// <summary>流式增量：参数为「去掉情绪标签后的当前完整正文」。</summary>
        public event Action<string> OnPartialReply;

        /// <summary>解析出情绪时触发（通常在流式早期）。</summary>
        public event Action<Emotion> OnEmotion;

        /// <summary>回复结束：参数为最终情绪与正文。</summary>
        public event Action<Emotion, string> OnCompleteReply;

        public event Action<string> OnError;

        public DialogueManager(ILLMProvider provider, PersonaConfig persona, MemoryStore memory)
        {
            _provider = provider;
            _persona = persona;
            _memory = memory;
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
            });
        }

        private List<ChatMessage> BuildMessages(string userInput)
        {
            var list = new List<ChatMessage>
            {
                new ChatMessage(Role.System, _persona.BuildSystemPrompt())
            };
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
