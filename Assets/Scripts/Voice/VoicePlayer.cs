using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// 语音播放器：把 TTS 返回的音频字节解码成 AudioClip 并播放。
    /// 通过临时文件 + UnityWebRequestMultimedia 解码（桌面端 wav/mp3 均可）。
    /// 暴露 <see cref="AudioSource"/> 供口型驱动读取输出波形。
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    public class VoicePlayer : MonoBehaviour
    {
        [SerializeField] private AudioSource _source;

        public AudioSource Source => _source;
        public bool IsSpeaking => _source != null && _source.isPlaying;

        private void Awake()
        {
            if (_source == null) _source = GetComponent<AudioSource>();
            if (_source == null) _source = gameObject.AddComponent<AudioSource>();
            _source.playOnAwake = false;
        }

        /// <summary>播放音频字节。ext 用于选择解码器（wav / mp3）。</summary>
        public void Play(byte[] audio, string ext = "wav")
        {
            if (audio == null || audio.Length == 0) return;
            StartCoroutine(PlayRoutine(audio, ext));
        }

        public void Stop()
        {
            if (_source != null) _source.Stop();
        }

        private IEnumerator PlayRoutine(byte[] audio, string ext)
        {
            string path = Path.Combine(Application.temporaryCachePath,
                $"tts_{DateTime.Now.Ticks}.{ext}");
            File.WriteAllBytes(path, audio);

            AudioType type = ext.ToLowerInvariant() == "mp3" ? AudioType.MPEG : AudioType.WAV;
            using (var req = UnityWebRequestMultimedia.GetAudioClip("file://" + path, type))
            {
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                {
                    var clip = DownloadHandlerAudioClip.GetContent(req);
                    _source.clip = clip;
                    _source.Play();
                }
                else
                {
                    Debug.LogError($"[VoicePlayer] 解码/播放失败: {req.error}");
                }
            }

            try { File.Delete(path); } catch { /* 忽略清理失败 */ }
        }
    }
}
