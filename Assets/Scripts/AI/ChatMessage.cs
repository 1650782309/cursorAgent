using System;

namespace DesktopCompanion.AI
{
    public enum Role
    {
        System,
        User,
        Assistant
    }

    /// <summary>一条对话消息。</summary>
    [Serializable]
    public class ChatMessage
    {
        public Role role;
        public string content;

        public ChatMessage(Role role, string content)
        {
            this.role = role;
            this.content = content;
        }

        /// <summary>OpenAI 协议的 role 字段（小写）。</summary>
        public string WireRole => role.ToString().ToLowerInvariant();
    }
}
