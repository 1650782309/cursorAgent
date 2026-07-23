using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json.Linq;

namespace DesktopCompanion.Voice
{
    /// <summary>
    /// OpenAI 兼容的 ASR 实现：POST {baseUrl}/audio/transcriptions，
    /// multipart/form-data 上传音频文件，返回 { "text": "..." }。
    /// </summary>
    public class OpenAICompatibleSTT : ISpeechToText
    {
        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(2)
        };

        private readonly ASRConfig _config;

        public OpenAICompatibleSTT(ASRConfig config) => _config = config;

        public async Task<string> TranscribeAsync(byte[] wavAudio, CancellationToken cancellationToken)
        {
            if (wavAudio == null || wavAudio.Length == 0) return "";

            string url = _config.baseUrl.TrimEnd('/') + "/audio/transcriptions";

            using var form = new MultipartFormDataContent();
            var fileContent = new ByteArrayContent(wavAudio);
            fileContent.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
            form.Add(fileContent, "file", "audio.wav");
            form.Add(new StringContent(_config.model), "model");
            if (!string.IsNullOrEmpty(_config.language))
                form.Add(new StringContent(_config.language), "language");

            using var request = new HttpRequestMessage(HttpMethod.Post, url) { Content = form };
            if (!string.IsNullOrEmpty(_config.apiKey))
                request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + _config.apiKey);

            using var response = await Http.SendAsync(request, cancellationToken);
            response.EnsureSuccessStatusCode();

            string body = await response.Content.ReadAsStringAsync();
            try
            {
                return JObject.Parse(body)["text"]?.ToString()?.Trim() ?? "";
            }
            catch
            {
                // 有的服务在 response_format=text 时直接返回纯文本。
                return body.Trim();
            }
        }
    }
}
