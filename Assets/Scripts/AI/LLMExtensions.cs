using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace DesktopCompanion.AI
{
    public static class LLMExtensions
    {
        /// <summary>
        /// 在流式接口之上封装一个「等待完整回复」的便捷方法，用于摘要等一次性任务。
        /// </summary>
        public static async Task<string> CompleteAsync(this ILLMProvider provider,
            IReadOnlyList<ChatMessage> messages, CancellationToken ct = default)
        {
            var sb = new StringBuilder();
            await provider.ChatStreamAsync(messages, delta => sb.Append(delta), ct);
            return sb.ToString();
        }
    }
}
