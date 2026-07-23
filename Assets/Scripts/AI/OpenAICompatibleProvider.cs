using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace DesktopCompanion.AI
{
    /// <summary>
    /// OpenAI 兼容供应商。一份实现同时覆盖：
    /// - 千问（DashScope compatible-mode: https://dashscope.aliyuncs.com/compatible-mode/v1）
    /// - DeepSeek（https://api.deepseek.com/v1）
    /// - 本地 Ollama（http://localhost:11434/v1）
    /// 差异仅由 <see cref="LLMConfig"/> 决定。
    /// </summary>
    public class OpenAICompatibleProvider : ILLMProvider
    {
        private static readonly HttpClient Http = new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(5)
        };

        private readonly LLMConfig _config;

        public OpenAICompatibleProvider(LLMConfig config) => _config = config;

        public string Name => _config.name;

        public async Task ChatStreamAsync(IReadOnlyList<ChatMessage> messages,
            Action<string> onDelta, CancellationToken cancellationToken)
        {
            string url = _config.baseUrl.TrimEnd('/') + "/chat/completions";

            var payload = new
            {
                model = _config.model,
                temperature = _config.temperature,
                stream = _config.stream,
                messages = BuildMessages(messages)
            };

            using var request = new HttpRequestMessage(HttpMethod.Post, url);
            if (!string.IsNullOrEmpty(_config.apiKey))
                request.Headers.TryAddWithoutValidation("Authorization", "Bearer " + _config.apiKey);
            request.Content = new StringContent(
                JsonConvert.SerializeObject(payload), Encoding.UTF8, "application/json");

            using var response = await Http.SendAsync(
                request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            response.EnsureSuccessStatusCode();

            if (!_config.stream)
            {
                string body = await response.Content.ReadAsStringAsync();
                onDelta?.Invoke(ExtractFullContent(body));
                return;
            }

            using var stream = await response.Content.ReadAsStreamAsync();
            using var reader = new StreamReader(stream);

            string line;
            while ((line = await reader.ReadLineAsync()) != null)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (string.IsNullOrWhiteSpace(line)) continue;
                if (!line.StartsWith("data:")) continue;

                string data = line.Substring("data:".Length).Trim();
                if (data == "[DONE]") break;

                string delta = ExtractDelta(data);
                if (!string.IsNullOrEmpty(delta)) onDelta?.Invoke(delta);
            }
        }

        private static List<object> BuildMessages(IReadOnlyList<ChatMessage> messages)
        {
            var list = new List<object>(messages.Count);
            foreach (var m in messages)
                list.Add(new { role = m.WireRole, content = m.content });
            return list;
        }

        private static string ExtractDelta(string data)
        {
            try
            {
                return JObject.Parse(data)["choices"]?[0]?["delta"]?["content"]?.ToString();
            }
            catch
            {
                return null;
            }
        }

        private static string ExtractFullContent(string body)
        {
            try
            {
                return JObject.Parse(body)["choices"]?[0]?["message"]?["content"]?.ToString() ?? "";
            }
            catch
            {
                return "";
            }
        }
    }
}
