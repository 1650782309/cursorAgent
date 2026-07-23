using System;

namespace DesktopCompanion.Brain
{
    /// <summary>
    /// 角色人设。转成 System Prompt 注入对话，决定语气、性格与行为约束。
    /// </summary>
    [Serializable]
    public class PersonaConfig
    {
        public string name = "小助";
        public string persona =
            "你是一个陪伴用户的桌面虚拟角色，性格温柔、俏皮、体贴，说话简洁自然，像朋友一样。";

        /// <summary>
        /// 情绪协议：要求模型在回复正文前输出一个情绪标签，便于驱动表情动画。
        /// 例：[emotion:happy] 今天也要加油哦！
        /// </summary>
        public string emotionInstruction =
            "每次回复请在正文最前面用方括号标注你此刻的情绪，格式严格为 " +
            "[emotion:X]，X 取值之一：neutral, happy, sad, angry, surprised, relaxed, shy, sleepy。" +
            "标签之后紧跟正常回复内容，不要额外解释这个标签。";

        public string BuildSystemPrompt()
        {
            return $"你的名字是{name}。{persona}\n{emotionInstruction}";
        }
    }
}
