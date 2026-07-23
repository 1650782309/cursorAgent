using System;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// OpenAI 兼容的 TTS 实现：POST {baseUrl}/audio/speech，请求体
    /// { model, input, voice, response_format }，返回音频二进制。
    /// </summary>
    public class OpenAICompatibleTTS : ITextToSpeech
    {
        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(2)
        };

        private readonly TTSConfig _config;

        public OpenAICompatibleTTS(TTSConfig config) => _config = config;

        public string Format => _config.format;

        public async Task<byte[]> SynthesizeAsync(string text, CancellationToken cancellationToken)
        {
            string url = _config.baseUrl.TrimEnd('/') + "/audio/speech";

            var payload = new
            {
                model = _config.model,
                input = text,
                voice = _config.voice,
                response_format = _config.format
            };

            using var request = new HttpRequestMessage(HttpMethod.Post, url);
            if (!string.IsNullOrEmpty(_config.apiKey))
                request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + _config.apiKey);
            request.Content = new StringContent(
                JsonConvert.SerializeObject(payload), Encoding.UTF8, "application/json");

            using var response = await Http.SendAsync(request, cancellationToken);
            response.EnsureSuccessStatusCode();
            return await response.Content.ReadAsByteArrayAsync();
        }
    }
}
