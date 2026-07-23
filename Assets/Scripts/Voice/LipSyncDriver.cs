using UnityEngine;
using DesktopCompanion.Rendering;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 简易口型同步：读取正在播放的语音输出波形，计算响度(RMS)，
    /// 平滑后映射到角色的 "aa" viseme 张嘴幅度。
    ///
    /// 这是"音量驱动"方案：实现简单、鲁棒、跨模型通用。若需更精细的
    /// 元音识别口型（aa/ih/ou/ee/oh 区分），后续可接入音素分析或对齐信息。
    /// </summary>
    public class LipSyncDriver : MonoBehaviour
    {
        [SerializeField] private VoicePlayer _voice;
        [SerializeField] private CharacterManager _character;

        [Tooltip("响度到张嘴幅度的增益")]
        [SerializeField] private float _gain = 8f;

        [Tooltip("张嘴/闭嘴的平滑速度")]
        [SerializeField] private float _smoothing = 18f;

        private readonly float[] _samples = new float[256];
        private float _current;

        private void Awake()
        {
            if (_voice == null) _voice = FindObjectOfType<VoicePlayer>();
            if (_character == null) _character = FindObjectOfType<CharacterManager>();
        }

        private void Update()
        {
            if (_character == null) return;

            float target = 0f;
            if (_voice != null && _voice.IsSpeaking && _voice.Source != null)
            {
                _voice.Source.GetOutputData(_samples, 0);
                float sum = 0f;
                for (int i = 0; i < _samples.Length; i++)
                    sum += _samples[i] * _samples[i];
                float rms = Mathf.Sqrt(sum / _samples.Length);
                target = Mathf.Clamp01(rms * _gain);
            }

            _current = Mathf.Lerp(_current, target, Time.deltaTime * _smoothing);
            _character.SetViseme("aa", _current);
        }
    }
}
