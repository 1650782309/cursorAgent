using UnityEngine;
using DesktopCompanion.App;
using DesktopCompanion.Core;
using DesktopCompanion.Voice;

namespace DesktopCompanion.UI
{
    /// <summary>
    /// 最简 IMGUI 调试对话框：一个输入框 + 一块回复气泡 + 语音输入状态。
    /// 目的是让脚手架"开箱即可对话验证"，无需先搭 Canvas。
    /// 生产环境建议替换为 uGUI/TextMeshPro 的美观气泡。
    /// </summary>
    public class ChatDebugUI : MonoBehaviour
    {
        [SerializeField] private AppBootstrap _app;
        [SerializeField] private VoiceInputController _voiceInput;

        private string _input = "";
        private string _reply = "";
        private string _heard = "";
        private Emotion _emotion = Emotion.Neutral;
        private bool _hooked;

        private void Awake()
        {
            if (_voiceInput == null) _voiceInput = FindObjectOfType<VoiceInputController>();
        }

        private void Update()
        {
            if (_hooked || _app == null || _app.Dialogue == null) return;
            _app.Dialogue.OnPartialReply += text => _reply = text;
            _app.Dialogue.OnEmotion += e => _emotion = e;
            if (_voiceInput != null) _voiceInput.OnTranscribed += text => _heard = text;
            _hooked = true;
        }

        private void OnGUI()
        {
            const int w = 360;
            var area = new Rect(Screen.width - w - 16, 16, w, 230);
            GUILayout.BeginArea(area, GUI.skin.box);

            GUILayout.Label($"情绪: {_emotion}");
            GUILayout.Label(string.IsNullOrEmpty(_reply) ? "(等待对话...)" : _reply);

            if (_voiceInput != null)
            {
                string status = _voiceInput.IsRecording ? "● 录音中..."
                    : _voiceInput.IsBusy ? "识别中..." : "按住语音键说话";
                GUILayout.Label($"🎤 {status}");
                if (!string.IsNullOrEmpty(_heard)) GUILayout.Label($"你说: {_heard}");
            }

            GUILayout.FlexibleSpace();
            GUILayout.BeginHorizontal();
            GUI.SetNextControlName("chatInput");
            _input = GUILayout.TextField(_input, GUILayout.MinWidth(240));

            bool enterPressed = Event.current.type == EventType.KeyDown
                                && Event.current.keyCode == KeyCode.Return
                                && GUI.GetNameOfFocusedControl() == "chatInput";

            if (GUILayout.Button("发送", GUILayout.Width(60)) || enterPressed)
            {
                Send();
            }
            GUILayout.EndHorizontal();
            GUILayout.EndArea();
        }

        private void Send()
        {
            if (_app?.Dialogue == null || string.IsNullOrWhiteSpace(_input)) return;
            _reply = "";
            _app.Dialogue.Send(_input.Trim());
            _input = "";
        }
    }
}
