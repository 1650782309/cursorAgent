using System;

namespace DesktopCompanion.Core
{
    /// <summary>角色资源类型：决定使用哪个渲染后端。</summary>
    public enum CharacterKind
    {
        Spine2D,
        Vrm3D
    }

    /// <summary>
    /// 一个角色的资源描述。业务层只面向该描述与 <see cref="ICharacterRenderer"/>，
    /// 不关心底层是 Spine 还是 VRM。
    /// </summary>
    [Serializable]
    public class CharacterAsset
    {
        /// <summary>角色唯一 id。</summary>
        public string id = "default";

        /// <summary>资源类型（决定渲染后端）。</summary>
        public CharacterKind kind = CharacterKind.Vrm3D;

        /// <summary>
        /// 资源路径。
        /// - VRM：.vrm 文件路径（StreamingAssets 相对路径或绝对路径）。
        /// - Spine：SkeletonDataAsset 的 Resources 路径。
        /// </summary>
        public string resourcePath = "";

        /// <summary>初始形态：Spine=skin 名，VRM=服装/切换标识（可空）。</summary>
        public string defaultForm = "";

        /// <summary>初始待机动画名。</summary>
        public string idleMotion = "idle";
    }
}
