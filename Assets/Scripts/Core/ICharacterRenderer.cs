using System.Threading.Tasks;
using UnityEngine;

namespace DesktopCompanion.Core
{
    /// <summary>
    /// 角色渲染抽象层 —— 「身体」的统一契约。
    ///
    /// 业务/大脑层（对话、情绪、记忆）只依赖此接口，因此无论底层是
    /// Spine（2D）还是 VRM（3D），甚至将来换其他方案，上层逻辑都无需改动。
    /// 每种后端（<see cref="Rendering.SpineCharacterRenderer"/>、
    /// <see cref="Rendering.VrmCharacterRenderer"/>）各自实现本接口。
    /// </summary>
    public interface ICharacterRenderer
    {
        CharacterKind Kind { get; }

        /// <summary>加载角色资源（异步）。</summary>
        Task LoadAsync(CharacterAsset asset);

        /// <summary>播放一段动作/动画，如 idle、wave、sleep。</summary>
        void PlayMotion(string motion, bool loop = true);

        /// <summary>设置情绪表情。VRM 映射到标准表情预设，Spine 映射到情绪动画。</summary>
        void SetExpression(Emotion emotion, float weight = 1f);

        /// <summary>切换形态。Spine=skin，VRM=服装/模型切换。</summary>
        void SetForm(string form);

        /// <summary>视线朝向世界坐标点（3D 有效，2D 可空实现）。</summary>
        void LookAt(Vector3 worldPoint);

        /// <summary>口型驱动（语音时使用）。viseme 如 aa/ih/ou/ee/oh。</summary>
        void SetViseme(string viseme, float weight);

        /// <summary>点击命中检测：用于窗口点击穿透判断。</summary>
        bool HitTest(Ray ray);

        /// <summary>每帧更新（动画混合、弹簧骨骼、视线插值等）。</summary>
        void Tick(float deltaTime);

        void Dispose();
    }
}
