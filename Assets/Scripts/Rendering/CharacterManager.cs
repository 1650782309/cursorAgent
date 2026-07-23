using System.Threading.Tasks;
using UnityEngine;
using DesktopCompanion.Core;

namespace DesktopCompanion.Rendering
{
    /// <summary>
    /// 角色管理器：持有当前 <see cref="ICharacterRenderer"/>，根据 <see cref="CharacterKind"/>
    /// 选择后端，并把统一指令转发给它。这是「身体」的入口。
    ///
    /// 注意：命名为 CharacterManager 而非 CharacterController，以避免与 Unity 内置的
    /// UnityEngine.CharacterController 组件冲突。
    /// </summary>
    public class CharacterManager : MonoBehaviour
    {
        [SerializeField] private Camera _camera;

        [Tooltip("对话气泡锚点相对角色根节点的高度（米），VRM 约 1.6 接近头顶")]
        [SerializeField] private float _bubbleHeight = 1.6f;

        public ICharacterRenderer Active { get; private set; }

        public Camera Camera => _camera;

        /// <summary>对话气泡的世界坐标锚点（角色头顶附近）。</summary>
        public Vector3 BubbleAnchorWorld => transform.position + Vector3.up * _bubbleHeight;

        private void Awake()
        {
            if (_camera == null) _camera = Camera.main;
        }

        /// <summary>按资源类型创建对应后端并加载。切换角色/形态时可重复调用。</summary>
        public async Task LoadCharacterAsync(CharacterAsset asset)
        {
            Active?.Dispose();
            Active = CreateRenderer(asset.kind);
            await Active.LoadAsync(asset);
        }

        private ICharacterRenderer CreateRenderer(CharacterKind kind)
        {
            switch (kind)
            {
                case CharacterKind.Spine2D:
                    return new SpineCharacterRenderer(transform);
                case CharacterKind.Vrm3D:
                default:
                    return new VrmCharacterRenderer(transform);
            }
        }

        // ---- 转发给当前后端的便捷方法（供大脑层调用）----
        public void PlayMotion(string motion, bool loop = true) => Active?.PlayMotion(motion, loop);
        public void SetExpression(Emotion e, float w = 1f) => Active?.SetExpression(e, w);
        public void SetForm(string form) => Active?.SetForm(form);
        public void SetViseme(string v, float w) => Active?.SetViseme(v, w);

        /// <summary>屏幕坐标是否命中角色（用于点击穿透判断）。</summary>
        public bool HitTestScreen(Vector2 screenPos)
        {
            if (Active == null || _camera == null) return false;
            Ray ray = _camera.ScreenPointToRay(screenPos);
            return Active.HitTest(ray);
        }

        private void Update()
        {
            float dt = Time.deltaTime;
            Active?.Tick(dt);

            // 3D 角色视线跟随鼠标（2D 后端为空实现）。
            if (Active != null && _camera != null)
            {
                var mouse = Input.mousePosition;
                var world = _camera.ScreenToWorldPoint(
                    new Vector3(mouse.x, mouse.y, 2f));
                Active.LookAt(world);
            }
        }

        private void OnDestroy() => Active?.Dispose();
    }
}
