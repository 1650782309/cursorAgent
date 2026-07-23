using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace DesktopCompanion.AI
{
    /// <summary>
    /// 模型供应商统一接口。所有后端（千问/DeepSeek/Ollama/本地）实现同一契约，
    /// 上层只面向此接口，切换模型只是换配置。
    /// </summary>
    public interface ILLMProvider
    {
        string Name { get; }

        /// <summary>
        /// 流式对话。每收到一个增量文本片段就回调一次 <paramref name="onDelta"/>。
        /// 注意：onDelta 可能在后台线程被调用，UI/Unity API 需自行切回主线程。
        /// </summary>
        Task ChatStreamAsync(IReadOnlyList<ChatMessage> messages,
            Action<string> onDelta,
            CancellationToken cancellationToken);
    }
}
