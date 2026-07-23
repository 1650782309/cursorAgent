using System.Text.RegularExpressions;
using DesktopCompanion.Core;

namespace DesktopCompanion.Brain
{
    /// <summary>
    /// 从模型回复中解析情绪标签 [emotion:xxx]，并返回去掉标签后的纯文本。
    /// </summary>
    public static class EmotionParser
    {
        private static readonly Regex TagRegex =
            new Regex(@"^\s*\[emotion:\s*(?<e>[a-zA-Z]+)\s*\]",
                RegexOptions.IgnoreCase | RegexOptions.Compiled);

        /// <summary>解析情绪。返回情绪 + 去掉标签的正文。</summary>
        public static (Emotion emotion, string cleanText) Parse(string reply)
        {
            if (string.IsNullOrEmpty(reply))
                return (Emotion.Neutral, reply ?? "");

            var match = TagRegex.Match(reply);
            if (!match.Success)
                return (Emotion.Neutral, reply);

            var emotion = MapName(match.Groups["e"].Value);
            string clean = reply.Substring(match.Length).TrimStart();
            return (emotion, clean);
        }

        private static Emotion MapName(string name)
        {
            switch (name.ToLowerInvariant())
            {
                case "happy": return Emotion.Happy;
                case "sad": return Emotion.Sad;
                case "angry": return Emotion.Angry;
                case "surprised": return Emotion.Surprised;
                case "relaxed": return Emotion.Relaxed;
                case "shy": return Emotion.Shy;
                case "sleepy": return Emotion.Sleepy;
                default: return Emotion.Neutral;
            }
        }
    }
}
