using System.Threading.Tasks;
using UnityEngine;
using DesktopCompanion.Core;

namespace DesktopCompanion.Rendering
{
    /// <summary>
    /// 3D 后端：基于 UniVRM。
    ///
    /// 安装 UniVRM 后，在 Player Settings → Scripting Define Symbols 添加
    /// <c>UNIVRM_PRESENT</c> 以启用真实实现；否则使用占位实现（保证工程可编译）。
    ///
    /// VRM 的优势：标准化表情预设（happy/angry/sad/relaxed/surprised）、
    /// 标准 viseme 口型（aa/ih/ou/ee/oh）、SpringBone 物理、LookAt 视线。
    /// </summary>
    public class VrmCharacterRenderer : ICharacterRenderer
    {
        public CharacterKind Kind => CharacterKind.Vrm3D;

        private GameObject _root;
        private readonly Transform _parent;

        public VrmCharacterRenderer(Transform parent)
        {
            _parent = parent;
        }

#if UNIVRM_PRESENT
        // 真实实现：使用 UniVRM 运行时加载。
        // 关键类型：UniVRM10.Vrm10.LoadPathAsync / Vrm10Instance /
        //          Vrm10Runtime.Expression / LookAtTargetType 等。
        private UniVRM10.Vrm10Instance _instance;

        public async Task LoadAsync(CharacterAsset asset)
        {
            string path = ResolvePath(asset.resourcePath);
            _instance = await UniVRM10.Vrm10.LoadPathAsync(path, canLoadVrm0X: true);
            if (_instance != null)
            {
                _root = _instance.gameObject;
                _root.transform.SetParent(_parent, false);
            }
        }

        public void SetExpression(Emotion emotion, float weight = 1f)
        {
            if (_instance == null) return;
            var runtime = _instance.Runtime;
            // 先清零常用表情，再设置目标情绪，避免叠加。
            runtime.Expression.SetWeight(UniVRM10.ExpressionKey.Happy, 0);
            runtime.Expression.SetWeight(UniVRM10.ExpressionKey.Angry, 0);
            runtime.Expression.SetWeight(UniVRM10.ExpressionKey.Sad, 0);
            runtime.Expression.SetWeight(UniVRM10.ExpressionKey.Relaxed, 0);
            runtime.Expression.SetWeight(UniVRM10.ExpressionKey.Surprised, 0);

            var key = MapEmotion(emotion);
            if (key.HasValue) runtime.Expression.SetWeight(key.Value, weight);
        }

        private static UniVRM10.ExpressionKey? MapEmotion(Emotion e)
        {
            switch (e)
            {
                case Emotion.Happy: return UniVRM10.ExpressionKey.Happy;
                case Emotion.Angry: return UniVRM10.ExpressionKey.Angry;
                case Emotion.Sad: return UniVRM10.ExpressionKey.Sad;
                case Emotion.Relaxed:
                case Emotion.Sleepy: return UniVRM10.ExpressionKey.Relaxed;
                case Emotion.Surprised: return UniVRM10.ExpressionKey.Surprised;
                default: return null;
            }
        }

        public void SetViseme(string viseme, float weight)
        {
            if (_instance == null) return;
            var key = viseme switch
            {
                "aa" => UniVRM10.ExpressionKey.Aa,
                "ih" => UniVRM10.ExpressionKey.Ih,
                "ou" => UniVRM10.ExpressionKey.Ou,
                "ee" => UniVRM10.ExpressionKey.Ee,
                "oh" => UniVRM10.ExpressionKey.Oh,
                _ => (UniVRM10.ExpressionKey?)null
            };
            if (key.HasValue) _instance.Runtime.Expression.SetWeight(key.Value, weight);
        }

        public void LookAt(Vector3 worldPoint)
        {
            if (_instance == null) return;
            _instance.Runtime.LookAt.LookAtInput =
                new UniVRM10.LookAtInput { WorldPosition = worldPoint };
        }
#else
        // 占位实现：未安装 UniVRM 时保证工程可编译，并给出提示。
        public Task LoadAsync(CharacterAsset asset)
        {
            _root = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            _root.name = "VRM_Placeholder(" + asset.id + ")";
            _root.transform.SetParent(_parent, false);
            Debug.LogWarning("[VrmCharacterRenderer] 占位模式：安装 UniVRM 并定义 UNIVRM_PRESENT 后加载真实 VRM。");
            return Task.CompletedTask;
        }

        public void SetExpression(Emotion emotion, float weight = 1f)
            => Debug.Log($"[VRM/占位] 表情 -> {emotion} ({weight})");

        public void SetViseme(string viseme, float weight) { }

        public void LookAt(Vector3 worldPoint)
        {
            if (_root != null) _root.transform.LookAt(worldPoint);
        }
#endif

        public void PlayMotion(string motion, bool loop = true)
        {
            // 动作播放通常走 Animator（Humanoid 重定向）。此处留作装配点：
            // 将 Mixamo/自制动画接到 VRM 的 Animator，再按 motion 名切换状态。
            Debug.Log($"[VRM] PlayMotion({motion}, loop={loop})");
        }

        public void SetForm(string form)
        {
            // VRM 换装：切换不同 VRM 实例，或启用/禁用可选网格。
            Debug.Log($"[VRM] SetForm({form})");
        }

        public bool HitTest(Ray ray)
        {
            if (_root == null) return false;
            // 简化：对根对象所有 Collider 做射线检测。真实项目建议加一个专门的碰撞体。
            foreach (var col in _root.GetComponentsInChildren<Collider>())
            {
                if (col.Raycast(ray, out _, 100f)) return true;
            }
            return false;
        }

        public void Tick(float deltaTime) { }

        public void Dispose()
        {
            if (_root != null) Object.Destroy(_root);
            _root = null;
        }

        private static string ResolvePath(string path)
        {
            if (System.IO.Path.IsPathRooted(path)) return path;
            return System.IO.Path.Combine(Application.streamingAssetsPath, path);
        }
    }
}
