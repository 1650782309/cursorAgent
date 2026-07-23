using UnityEngine;
using UnityEngine.UI;

namespace DesktopCompanion.UI
{
    /// <summary>
    /// 运行时构建 uGUI 的小工具：创建带 CJK 动态字体的 Text、Panel、InputField 等，
    /// 避免依赖 TMP Essentials 导入，做到"开箱即用"。
    /// </summary>
    public static class UiFactory
    {
        private static Font _font;

        /// <summary>获取一个支持中文的动态字体（优先各平台常见 CJK 字体，回退内置字体）。</summary>
        public static Font Font
        {
            get
            {
                if (_font != null) return _font;
                string[] candidates =
                {
                    "Microsoft YaHei", "PingFang SC", "Heiti SC",
                    "Noto Sans CJK SC", "SimHei", "Arial"
                };
                try { _font = UnityEngine.Font.CreateDynamicFontFromOSFont(candidates, 24); }
                catch { /* ignore */ }

                if (_font == null)
                {
                    _font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf")
                            ?? Resources.GetBuiltinResource<Font>("Arial.ttf");
                }
                return _font;
            }
        }

        public static RectTransform CreatePanel(string name, Transform parent, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            go.GetComponent<Image>().color = color;
            return go.GetComponent<RectTransform>();
        }

        public static Text CreateText(string name, Transform parent, int fontSize,
            TextAnchor anchor = TextAnchor.UpperLeft)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Text));
            go.transform.SetParent(parent, false);
            var text = go.GetComponent<Text>();
            text.font = Font;
            text.fontSize = fontSize;
            text.color = Color.black;
            text.alignment = anchor;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            text.supportRichText = true;
            return text;
        }

        public static void Stretch(RectTransform rt, float left, float top, float right, float bottom)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = new Vector2(left, bottom);
            rt.offsetMax = new Vector2(-right, -top);
        }
    }
}
