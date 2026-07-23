using System.Threading;
using UnityEngine;
using DesktopCompanion.AI;
using DesktopCompanion.Brain;
using DesktopCompanion.Core;
using DesktopCompanion.Rendering;
using DesktopCompanion.Voice;

namespace DesktopCompanion.App
{
    /// <summary>
    /// 应用装配入口：把「大脑」（AI/人设/记忆/对话）与「身体」（角色渲染 + 语音）连接起来。
    ///
    /// 场景使用方法：
    /// 1. 新建空 GameObject，挂载本脚本；
    /// 2. 场景中放一个挂 <see cref="CharacterManager"/> 的 GameObject 并拖到字段上；
    /// 3. （可选）挂 <see cref="VoicePlayer"/> + <see cref="LipSyncDriver"/> 启用语音与口型；
    /// 4. （可选）放 UniWindowController Prefab + DesktopWindowManager。
    /// </summary>
    public class AppBootstrap : MonoBehaviour
    {
        [Header("身体：角色渲染")]
        [SerializeField] private CharacterManager _character;

        [Header("语音（可选）")]
        [SerializeField] private VoicePlayer _voice;

        [Header("默认加载的角色")]
        [SerializeField] private CharacterKind _kind = CharacterKind.Vrm3D;
        [SerializeField] private string _resourcePath = "avatar.vrm";
        [SerializeField] private string _defaultForm = "";

        /// <summary>大脑对外入口，供 UI 调用。</summary>
        public DialogueManager Dialogue { get; private set; }

        /// <summary>语音识别入口，供 VoiceInputController 使用（未启用时为 null）。</summary>
        public ISpeechToText STT { get; private set; }

        private ITextToSpeech _tts;
        private TTSConfig _ttsConfig;
        private CancellationTokenSource _speakCts;

        private async void Start()
        {
            // 确保主线程调度器存在。
            _ = MainThreadDispatcher.Instance;

            // ---- 组装大脑 ----
            var llmConfig = LLMManager.LoadConfig();
            ILLMProvider provider = LLMManager.CreateProvider(llmConfig);
            var persona = PersonaLoader.Load();
            var memory = new MemoryStore(hardCap: 40);
            var summarizer = new MemorySummarizer(provider);
            Dialogue = new DialogueManager(provider, persona, memory, summarizer);

            Debug.Log($"[AppBootstrap] 使用模型供应商: {provider.Name}");

            // ---- 组装语音输出（TTS，可选）----
            _ttsConfig = TTSManager.LoadConfig();
            if (_ttsConfig.enabled)
            {
                _tts = TTSManager.CreateProvider(_ttsConfig);
                if (_voice == null) _voice = FindObjectOfType<VoicePlayer>();
                Debug.Log("[AppBootstrap] TTS 已启用");
            }

            // ---- 组装语音输入（ASR，可选）----
            var asrConfig = ASRManager.LoadConfig();
            if (asrConfig.enabled)
            {
                STT = ASRManager.CreateProvider(asrConfig);
                var voiceInput = FindObjectOfType<VoiceInputController>();
                voiceInput?.Configure(asrConfig.pushToTalkKey, asrConfig.sampleRate);
                Debug.Log($"[AppBootstrap] ASR 已启用（按住 {asrConfig.pushToTalkKey} 说话）");
            }

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

            // ---- 连接大脑 -> 身体：情绪驱动表情/动作 ----
            Dialogue.OnEmotion += emotion =>
            {
                _character?.SetExpression(emotion);
                _character?.PlayMotion(MotionForEmotion(emotion));
            };

            // ---- 连接大脑 -> 语音：回复完成后朗读（驱动口型）----
            Dialogue.OnCompleteReply += (_, text) => Speak(text);

            Dialogue.OnError += err => Debug.LogError($"[Dialogue] {err}");
        }

        private async void Speak(string text)
        {
            if (_tts == null || _voice == null || string.IsNullOrWhiteSpace(text)) return;

            _speakCts?.Cancel();
            _speakCts = new CancellationTokenSource();
            try
            {
                byte[] audio = await _tts.SynthesizeAsync(text, _speakCts.Token);
                MainThreadDispatcher.Instance.Enqueue(() => _voice.Play(audio, _tts.Format));
            }
            catch (System.OperationCanceledException) { }
            catch (System.Exception e)
            {
                Debug.LogWarning($"[AppBootstrap] 语音合成失败: {e.Message}");
            }
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
