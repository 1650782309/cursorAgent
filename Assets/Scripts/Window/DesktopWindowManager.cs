using UnityEngine;

namespace DesktopCompanion.Window
{
    /// <summary>
    /// 桌面悬浮窗管理：透明背景、始终置顶、点击穿透、可拖动。
    ///
    /// 依赖 UniWindowController（免费资产，桌宠/VTuber 标准做法）。
    /// 安装后在 Player Settings → Scripting Define Symbols 添加 <c>UNIWINDOW_PRESENT</c>
    /// 启用真实实现；否则为占位（保证工程可编译，编辑器内可正常预览）。
    ///
    /// 另需在 Player Settings 勾选：
    /// - Rendering → 取消 "Use DXGI Flip Model Swapchain"（Windows 透明需要）
    /// - Resolution → 关闭全屏，设 Windowed
    /// </summary>
    public class DesktopWindowManager : MonoBehaviour
    {
        [Tooltip("非角色区域是否穿透点击到桌面")]
        public bool clickThrough = true;

        [Tooltip("是否始终置顶")]
        public bool alwaysOnTop = true;

#if UNIWINDOW_PRESENT
        private Kirurobo.UniWindowController _uwc;

        private void Start()
        {
            _uwc = FindObjectOfType<Kirurobo.UniWindowController>();
            if (_uwc == null)
            {
                Debug.LogError("[DesktopWindowManager] 场景中缺少 UniWindowController，请添加其 Prefab。");
                return;
            }
            _uwc.isTransparent = true;
            _uwc.isTopmost = alwaysOnTop;
            // 命中透明像素时自动穿透；由 CharacterManager 的 HitTest 精细控制。
            _uwc.isClickThrough = false;
        }

        /// <summary>由外部（命中检测）每帧驱动：是否让鼠标穿透。</summary>
        public void SetClickThrough(bool through)
        {
            if (_uwc != null) _uwc.isClickThrough = through;
        }

        public void SetTopmost(bool top)
        {
            alwaysOnTop = top;
            if (_uwc != null) _uwc.isTopmost = top;
        }
#else
        private void Start()
        {
            Debug.LogWarning("[DesktopWindowManager] 占位模式：安装 UniWindowController 并定义 UNIWINDOW_PRESENT 后启用透明/穿透窗口。");
        }

        public void SetClickThrough(bool through) { }
        public void SetTopmost(bool top) => alwaysOnTop = top;
#endif
    }
}
