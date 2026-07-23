using UnityEngine;
using DesktopCompanion.Rendering;

namespace DesktopCompanion.Window
{
    /// <summary>
    /// 拖动角色移动整个桌面窗口（桌宠核心交互）。
    /// 仅当鼠标按在角色身上（命中检测）时才拖动，避免误拖。
    ///
    /// 依赖 UniWindowController 的 windowPosition（屏幕像素坐标，左上原点）。
    /// 未安装时为占位（编辑器内不移动窗口，仅打印日志）。
    /// </summary>
    [RequireComponent(typeof(DesktopWindowManager))]
    public class CharacterDragHandler : MonoBehaviour
    {
        [SerializeField] private CharacterManager _character;

        private bool _dragging;
        private Vector2 _grabScreenOffset;

        private void Awake()
        {
            if (_character == null) _character = FindObjectOfType<CharacterManager>();
        }

#if UNIWINDOW_PRESENT
        private Kirurobo.UniWindowController _uwc;

        private void Start()
        {
            _uwc = FindObjectOfType<Kirurobo.UniWindowController>();
        }

        private void Update()
        {
            if (_uwc == null || _character == null) return;

            if (Input.GetMouseButtonDown(0) && _character.HitTestScreen(Input.mousePosition))
            {
                _dragging = true;
                // 记录鼠标（屏幕坐标）与窗口左上角的偏移。
                Vector2 mouseScreen = MouseToWindowSpace(Input.mousePosition);
                _grabScreenOffset = mouseScreen - _uwc.windowPosition;
            }
            else if (Input.GetMouseButtonUp(0))
            {
                _dragging = false;
            }

            if (_dragging)
            {
                Vector2 mouseScreen = MouseToWindowSpace(Input.mousePosition);
                _uwc.windowPosition = mouseScreen - _grabScreenOffset;
            }
        }

        // Unity 鼠标坐标是窗口内左下原点，需转成桌面屏幕左上原点。
        private Vector2 MouseToWindowSpace(Vector3 mouse)
        {
            return _uwc.windowPosition + new Vector2(mouse.x, Screen.height - mouse.y);
        }
#else
        private void Update()
        {
            if (_character == null) return;
            if (Input.GetMouseButtonDown(0) && _character.HitTestScreen(Input.mousePosition))
            {
                _dragging = true;
                Debug.Log("[CharacterDragHandler] 占位模式：安装 UniWindowController 并定义 UNIWINDOW_PRESENT 后可拖动窗口。");
            }
            else if (Input.GetMouseButtonUp(0))
            {
                _dragging = false;
            }
        }
#endif
    }
}
