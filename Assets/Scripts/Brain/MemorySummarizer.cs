using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using DesktopCompanion.AI;

namespace DesktopCompanion.Brain
{
    /// <summary>
    /// 用 LLM 把旧对话压缩成简短摘要，作为长期记忆保留（避免上下文无限增长）。
    /// </summary>
    public class MemorySummarizer
    {
        private readonly ILLMProvider _provider;

        public MemorySummarizer(ILLMProvider provider) => _provider = provider;

        /// <summary>
        /// 结合已有摘要与一批旧对话，生成新的合并摘要。
        /// </summary>
        public async Task<string> SummarizeAsync(string existingSummary,
            IReadOnlyList<ChatMessage> older, CancellationToken ct = default)
        {
            if (older == null || older.Count == 0) return existingSummary ?? "";

            var sb = new StringBuilder();
            if (!string.IsNullOrEmpty(existingSummary))
                sb.AppendLine("已有的历史摘要：\n" + existingSummary + "\n");

            sb.AppendLine("以下是需要并入摘要的新对话：");
            foreach (var m in older)
                sb.AppendLine($"{m.WireRole}: {m.content}");

            var prompt = new List<ChatMessage>
            {
                new ChatMessage(Role.System,
                    "你是对话摘要助手。请把提供的历史摘要与新对话合并，" +
                    "用第三人称、简洁中文提炼出对后续陪伴有用的长期信息：" +
                    "用户的偏好、习惯、重要事实、情感状态与约定。只输出摘要本身，不要多余解释。"),
                new ChatMessage(Role.User, sb.ToString())
            };

            var result = await _provider.CompleteAsync(prompt, ct);
            return result?.Trim() ?? existingSummary ?? "";
        }
    }
}
