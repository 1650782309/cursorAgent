using UnityEngine;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 麦克风录音：用 Unity 内置 <see cref="Microphone"/> 采集，停止时导出 16-bit WAV 字节。
    /// </summary>
    public class MicrophoneRecorder : MonoBehaviour
    {
        [SerializeField] private int _sampleRate = 16000;
        [SerializeField] private int _maxSeconds = 60;

        private AudioClip _clip;
        private string _device;
        private bool _recording;

        public bool IsRecording => _recording;

        public void Configure(int sampleRate)
        {
            if (sampleRate > 0) _sampleRate = sampleRate;
        }

        public bool StartRecording()
        {
            if (_recording) return true;
            if (Microphone.devices.Length == 0)
            {
                Debug.LogWarning("[MicrophoneRecorder] 未检测到麦克风设备。");
                return false;
            }

            _device = Microphone.devices[0];
            _clip = Microphone.Start(_device, false, _maxSeconds, _sampleRate);
            _recording = _clip != null;
            return _recording;
        }

        /// <summary>停止录音并返回 WAV 字节（无有效音频时返回 null）。</summary>
        public byte[] StopRecording()
        {
            if (!_recording) return null;

            int position = Microphone.GetPosition(_device);
            Microphone.End(_device);
            _recording = false;

            if (_clip == null || position <= 0) return null;

            var samples = new float[position * _clip.channels];
            _clip.GetData(samples, 0);
            return WavUtility.FromSamples(samples, _clip.channels, _clip.frequency);
        }
    }
}
