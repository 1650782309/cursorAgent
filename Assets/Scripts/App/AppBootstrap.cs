using UnityEngine;
using DesktopCompanion.AI;
using DesktopCompanion.Brain;
using DesktopCompanion.Core;
using DesktopCompanion.Rendering;

namespace DesktopCompanion.App
{
    /// <summary>
    /// 应用装配入口：把「大脑」（AI/人设/记忆/对话）与「身体」（角色渲染）连接起来。
    ///
    /// 场景使用方法：
    /// 1. 新建空 GameObject，挂载本脚本；
    /// 2. 场景中放一个挂 <see cref="CharacterManager"/> 的 GameObject 并拖到字段上；
    /// 3. （可选）放 UniWindowController Prefab + DesktopWindowManager。
    /// </summary>
    public class AppBootstrap : MonoBehaviour
    {
        [Header("身体：角色渲染")]
        [SerializeField] private CharacterManager _character;

        [Header("默认加载的角色")]
        [SerializeField] private CharacterKind _kind = CharacterKind.Vrm3D;
        [SerializeField] private string _resourcePath = "avatar.vrm";
        [SerializeField] private string _defaultForm = "";

        /// <summary>大脑对外入口，供 UI 调用。</summary>
        public DialogueManager Dialogue { get; private set; }

        private async void Start()
        {
            // 确保主线程调度器存在。
            _ = MainThreadDispatcher.Instance;

            // ---- 组装大脑 ----
            var llmConfig = LLMManager.LoadConfig();
            ILLMProvider provider = LLMManager.CreateProvider(llmConfig);
            var persona = PersonaLoader.Load();
            var memory = new MemoryStore(maxTurns: 20);
            Dialogue = new DialogueManager(provider, persona, memory);

            Debug.Log($"[AppBootstrap] 使用模型供应商: {provider.Name}");

            // ---- 加载身体 ----
            if (_character == null) _character = FindObjectOfType<CharacterManager>();
            if (_character != null)
            {
                await _character.LoadCharacterAsync(new CharacterAsset
                {
                    id = "default",
                    kind = _kind,
                    resourcePath = _resourcePath,
                    defaultForm = _defaultForm
                });
            }

            // ---- 连接大脑 -> 身体：情绪驱动表情 ----
            Dialogue.OnEmotion += emotion =>
            {
                _character?.SetExpression(emotion);
                _character?.PlayMotion(MotionForEmotion(emotion));
            };

            Dialogue.OnError += err => Debug.LogError($"[Dialogue] {err}");
        }

        private static string MotionForEmotion(Emotion e)
        {
            switch (e)
            {
                case Emotion.Happy: return "happy";
                case Emotion.Sad: return "sad";
                case Emotion.Angry: return "angry";
                case Emotion.Sleepy: return "sleep";
                default: return "idle";
            }
        }
    }
}
