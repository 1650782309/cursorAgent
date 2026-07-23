using System.Threading.Tasks;
using UnityEngine;
using DesktopCompanion.Core;

namespace DesktopCompanion.Rendering
{
    /// <summary>
    /// 2D 后端：基于 spine-unity（Esoteric 官方运行时）。
    ///
    /// 安装 spine-unity 后，在 Player Settings → Scripting Define Symbols 添加
    /// <c>SPINE_UNITY</c> 以启用真实实现；否则使用占位实现（保证工程可编译）。
    ///
    /// 形态用 Spine 的 skin 切换，情绪用不同动画（track）表达。
    /// </summary>
    public class SpineCharacterRenderer : ICharacterRenderer
    {
        public CharacterKind Kind => CharacterKind.Spine2D;

        private GameObject _root;
        private readonly Transform _parent;

        public SpineCharacterRenderer(Transform parent)
        {
            _parent = parent;
        }

#if SPINE_UNITY
        private Spine.Unity.SkeletonAnimation _skeleton;

        public Task LoadAsync(CharacterAsset asset)
        {
            // resourcePath 指向放在 Resources 下的 SkeletonDataAsset。
            var dataAsset = Resources.Load<Spine.Unity.SkeletonDataAsset>(asset.resourcePath);
            if (dataAsset == null)
            {
                Debug.LogError($"[Spine] 找不到 SkeletonDataAsset: {asset.resourcePath}");
                return Task.CompletedTask;
            }

            _skeleton = Spine.Unity.SkeletonAnimation.NewSkeletonAnimationGameObject(dataAsset);
            _root = _skeleton.gameObject;
            _root.transform.SetParent(_parent, false);

            if (!string.IsNullOrEmpty(asset.defaultForm))
                SetForm(asset.defaultForm);
            if (!string.IsNullOrEmpty(asset.idleMotion))
                PlayMotion(asset.idleMotion, true);

            return Task.CompletedTask;
        }

        public void PlayMotion(string motion, bool loop = true)
        {
            if (_skeleton == null) return;
            _skeleton.AnimationState.SetAnimation(0, motion, loop);
        }

        public void SetExpression(Emotion emotion, float weight = 1f)
        {
            if (_skeleton == null) return;
            // 情绪 -> 动画名约定，用叠加轨道(track 1)表达。
            string anim = "emotion_" + emotion.ToString().ToLower();
            var entry = _skeleton.AnimationState.SetAnimation(1, anim, false);
            if (entry != null) entry.MixDuration = 0.2f;
        }

        public void SetForm(string form)
        {
            if (_skeleton == null) return;
            _skeleton.Skeleton.SetSkin(form);
            _skeleton.Skeleton.SetSlotsToSetupPose();
        }
#else
        public Task LoadAsync(CharacterAsset asset)
        {
            _root = GameObject.CreatePrimitive(PrimitiveType.Quad);
            _root.name = "Spine_Placeholder(" + asset.id + ")";
            _root.transform.SetParent(_parent, false);
            Debug.LogWarning("[SpineCharacterRenderer] 占位模式：安装 spine-unity 并定义 SPINE_UNITY 后加载真实骨架。");
            return Task.CompletedTask;
        }

        public void PlayMotion(string motion, bool loop = true)
            => Debug.Log($"[Spine/占位] PlayMotion({motion}, loop={loop})");

        public void SetExpression(Emotion emotion, float weight = 1f)
            => Debug.Log($"[Spine/占位] 表情 -> {emotion}");

        public void SetForm(string form)
            => Debug.Log($"[Spine/占位] SetForm({form})");
#endif

        // 2D 不需要视线/口型（口型可用嘴部 slot 动画实现，留待扩展）。
        public void LookAt(Vector3 worldPoint) { }
        public void SetViseme(string viseme, float weight) { }

        public bool HitTest(Ray ray)
        {
            if (_root == null) return false;
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
    }
}
