using UnityEngine;
using DesktopCompanion.Rendering;

namespace DesktopCompanion.Window
{
    /// <summary>
    /// 逐帧判定鼠标是否落在角色身上：命中 -> 可交互（不穿透），
    /// 未命中 -> 穿透到桌面/其他软件。是"只有人物能点、其余穿透"的关键逻辑。
    /// </summary>
    [RequireComponent(typeof(DesktopWindowManager))]
    public class ClickThroughController : MonoBehaviour
    {
        [SerializeField] private CharacterManager _character;
        private DesktopWindowManager _window;

        private bool _lastThrough;

        private void Awake()
        {
            _window = GetComponent<DesktopWindowManager>();
            if (_character == null) _character = FindObjectOfType<CharacterManager>();
        }

        private void Update()
        {
            if (_character == null || !_window.clickThrough) return;

            bool onCharacter = _character.HitTestScreen(Input.mousePosition);
            bool through = !onCharacter;

            if (through != _lastThrough)
            {
                _window.SetClickThrough(through);
                _lastThrough = through;
            }
        }
    }
}
