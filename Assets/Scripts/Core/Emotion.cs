namespace DesktopCompanion.Core
{
    /// <summary>
    /// 角色情绪。由 AI 回复解析得到，驱动表情/动画，与具体渲染后端无关。
    /// VRM 标准表情、Spine 情绪动画都映射到这一组枚举。
    /// </summary>
    public enum Emotion
    {
        Neutral,
        Happy,
        Sad,
        Angry,
        Surprised,
        Relaxed,
        Shy,
        Sleepy
    }
}
