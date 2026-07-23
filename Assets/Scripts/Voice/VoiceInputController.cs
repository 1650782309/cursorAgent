using System;
using UnityEngine;
using DesktopCompanion.App;
using DesktopCompanion.Brain;
using DesktopCompanion.Core;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 语音输入（按住说话）：按住指定键开始录音，松开后转写并送入对话大脑，
    /// 与上一轮的 TTS 合成「能听能说」闭环。
    /// </summary>
    public class VoiceInputController : MonoBehaviour
    {
        [SerializeField] private AppBootstrap _app;
        [SerializeField] private MicrophoneRecorder _recorder;
        [SerializeField] private KeyCode _pushToTalk = KeyCode.LeftAlt;

        /// <summary>转写完成事件（供 UI 显示用户说了什么）。</summary>
        public event Action<string> OnTranscribed;

        public bool IsRecording => _recorder != null && _recorder.IsRecording;
        public bool IsBusy { get; private set; }

        private void Awake()
        {
            if (_app == null) _app = FindObjectOfType<AppBootstrap>();
            if (_recorder == null) _recorder = FindObjectOfType<MicrophoneRecorder>();
        }

        /// <summary>由 AppBootstrap 用配置初始化按键与采样率。</summary>
        public void Configure(string keyName, int sampleRate)
        {
            if (!string.IsNullOrEmpty(keyName) && Enum.TryParse(keyName, out KeyCode key))
                _pushToTalk = key;
            _recorder?.Configure(sampleRate);
        }

        private void Update()
        {
            if (_app == null || _recorder == null || _app.STT == null) return;

            if (Input.GetKeyDown(_pushToTalk) && !IsBusy && !_recorder.IsRecording)
            {
                _recorder.StartRecording();
            }
            else if (Input.GetKeyUp(_pushToTalk) && _recorder.IsRecording)
            {
                byte[] wav = _recorder.StopRecording();
                if (wav != null) Transcribe(wav);
            }
        }

        private async void Transcribe(byte[] wav)
        {
            IsBusy = true;
            try
            {
                string text = await _app.STT.TranscribeAsync(wav, default);
                MainThreadDispatcher.Instance.Enqueue(() =>
                {
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        OnTranscribed?.Invoke(text);
                        _app.Dialogue?.Send(text);
                    }
                });
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[VoiceInputController] 语音识别失败: {e.Message}");
            }
            finally
            {
                IsBusy = false;
            }
        }
    }
}
