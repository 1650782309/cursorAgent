using System.Collections;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;
using DesktopCompanion.App;
using DesktopCompanion.Rendering;
using DesktopCompanion.Voice;

namespace DesktopCompanion.UI
{
    /// <summary>
    /// 运行时自建的对话界面（uGUI）：
    /// - 角色头顶的聊天气泡，流式显示 AI 回复，静默数秒后自动淡出；
    /// - 底部输入栏（输入框 + 发送按钮），回车/点击发送；
    /// - 语音转写结果作为"你说"临时显示。
    ///
    /// 全程用代码构建，无需在编辑器手动搭 Canvas；生产可按需替换为美术定制的预制体。
    /// </summary>
    public class ChatUI : MonoBehaviour
    {
        [SerializeField] private AppBootstrap _app;
        [SerializeField] private CharacterManager _character;
        [SerializeField] private VoiceInputController _voiceInput;

        [Header("气泡")]
        [SerializeField] private float _autoHideSeconds = 6f;
        [SerializeField] private Vector2 _bubbleSize = new Vector2(360, 150);

        private Canvas _canvas;
        private RectTransform _bubble;
        private Text _bubbleText;
        private CanvasGroup _bubbleGroup;
        private InputField _input;

        private Coroutine _hideRoutine;
        private bool _hooked;

        private void Awake()
        {
            if (_app == null) _app = FindObjectOfType<AppBootstrap>();
            if (_character == null) _character = FindObjectOfType<CharacterManager>();
            if (_voiceInput == null) _voiceInput = FindObjectOfType<VoiceInputController>();

            EnsureEventSystem();
            BuildCanvas();
            BuildBubble();
            BuildInputBar();
            SetBubbleVisible(false);
        }

        private void Update()
        {
            if (_hooked || _app == null || _app.Dialogue == null) return;

            _app.Dialogue.OnPartialReply += OnPartial;
            _app.Dialogue.OnCompleteReply += (_, __) => ScheduleHide();
            _app.Dialogue.OnError += err => ShowBubble("（出错了：" + err + "）");
            if (_voiceInput != null)
                _voiceInput.OnTranscribed += text => ShowBubble("你说：" + text, keepShort: true);
            _hooked = true;
        }

        private void LateUpdate()
        {
            if (_bubble == null || _character == null || _character.Camera == null) return;
            if (!_bubbleGroup.gameObject.activeSelf) return;

            Vector3 screen = _character.Camera.WorldToScreenPoint(_character.BubbleAnchorWorld);
            // 角色在相机背后时隐藏气泡。
            _bubbleGroup.alpha = screen.z < 0 ? 0f : _bubbleGroup.alpha;
            _bubble.position = screen;
        }

        // ---- 事件处理 ----
        private void OnPartial(string text)
        {
            ShowBubble(text);
        }

        private void ShowBubble(string text, bool keepShort = false)
        {
            if (_bubbleText == null) return;
            _bubbleText.text = text;
            SetBubbleVisible(true);
            _bubbleGroup.alpha = 1f;
            if (keepShort) ScheduleHide(2.5f);
            else CancelHide();
        }

        private void ScheduleHide(float seconds = -1f)
        {
            CancelHide();
            _hideRoutine = StartCoroutine(HideAfter(seconds < 0 ? _autoHideSeconds : seconds));
        }

        private void CancelHide()
        {
            if (_hideRoutine != null) { StopCoroutine(_hideRoutine); _hideRoutine = null; }
        }

        private IEnumerator HideAfter(float seconds)
        {
            yield return new WaitForSeconds(seconds);
            float t = 0f;
            while (t < 0.5f)
            {
                t += Time.deltaTime;
                _bubbleGroup.alpha = Mathf.Lerp(1f, 0f, t / 0.5f);
                yield return null;
            }
            SetBubbleVisible(false);
        }

        private void SetBubbleVisible(bool visible)
        {
            if (_bubbleGroup != null) _bubbleGroup.gameObject.SetActive(visible);
        }

        // 旧版 InputField 只有 onEndEdit（回车或失焦都会触发），
        // 故用按键判断只在回车时发送。
        private void OnEndEdit(string _)
        {
            if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
                SendCurrent();
        }

        private void SendCurrent()
        {
            if (_app?.Dialogue == null || _input == null) return;
            string text = _input.text?.Trim();
            if (string.IsNullOrEmpty(text)) return;
            _app.Dialogue.Send(text);
            _input.text = "";
            _input.ActivateInputField();
        }

        // ---- 构建 UI ----
        private void EnsureEventSystem()
        {
            if (FindObjectOfType<EventSystem>() == null)
            {
                var es = new GameObject("EventSystem",
                    typeof(EventSystem), typeof(StandaloneInputModule));
                DontDestroyOnLoad(es);
            }
        }

        private void BuildCanvas()
        {
            var go = new GameObject("ChatCanvas",
                typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            go.transform.SetParent(transform, false);
            _canvas = go.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            var scaler = go.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920, 1080);
        }

        private void BuildBubble()
        {
            _bubble = UiFactory.CreatePanel("Bubble", _canvas.transform,
                new Color(1f, 1f, 1f, 0.92f));
            _bubble.sizeDelta = _bubbleSize;
            _bubble.pivot = new Vector2(0.5f, 0f); // 底边中点对准头顶
            _bubbleGroup = _bubble.gameObject.AddComponent<CanvasGroup>();
            _bubbleGroup.interactable = false;
            _bubbleGroup.blocksRaycasts = false;

            _bubbleText = UiFactory.CreateText("Text", _bubble, 26, TextAnchor.UpperLeft);
            UiFactory.Stretch(_bubbleText.rectTransform, 16, 12, 16, 12);
        }

        private void BuildInputBar()
        {
            var bar = UiFactory.CreatePanel("InputBar", _canvas.transform,
                new Color(0f, 0f, 0f, 0.55f));
            bar.anchorMin = new Vector2(0.5f, 0f);
            bar.anchorMax = new Vector2(0.5f, 0f);
            bar.pivot = new Vector2(0.5f, 0f);
            bar.sizeDelta = new Vector2(640, 64);
            bar.anchoredPosition = new Vector2(0, 24);

            // 输入框
            var fieldRt = UiFactory.CreatePanel("Field", bar, new Color(1, 1, 1, 0.95f));
            fieldRt.anchorMin = new Vector2(0, 0);
            fieldRt.anchorMax = new Vector2(1, 1);
            fieldRt.offsetMin = new Vector2(12, 10);
            fieldRt.offsetMax = new Vector2(-104, -10);

            _input = fieldRt.gameObject.AddComponent<InputField>();
            var textComp = UiFactory.CreateText("Text", fieldRt, 24, TextAnchor.MiddleLeft);
            textComp.supportRichText = false;
            UiFactory.Stretch(textComp.rectTransform, 12, 4, 12, 4);
            var placeholder = UiFactory.CreateText("Placeholder", fieldRt, 24, TextAnchor.MiddleLeft);
            placeholder.text = "和 TA 聊点什么…（Enter 发送）";
            placeholder.color = new Color(0.4f, 0.4f, 0.4f, 1f);
            UiFactory.Stretch(placeholder.rectTransform, 12, 4, 12, 4);

            _input.textComponent = textComp;
            _input.placeholder = placeholder;
            _input.lineType = InputField.LineType.SingleLine;
            _input.targetGraphic = fieldRt.GetComponent<Image>();
            _input.onEndEdit.AddListener(OnEndEdit);

            // 发送按钮
            var btnRt = UiFactory.CreatePanel("Send", bar, new Color(0.2f, 0.5f, 1f, 1f));
            btnRt.anchorMin = new Vector2(1, 0);
            btnRt.anchorMax = new Vector2(1, 1);
            btnRt.pivot = new Vector2(1, 0.5f);
            btnRt.offsetMin = new Vector2(-96, 10);
            btnRt.offsetMax = new Vector2(-12, -10);
            btnRt.anchoredPosition = new Vector2(-12, 0);
            var btn = btnRt.gameObject.AddComponent<Button>();
            btn.targetGraphic = btnRt.GetComponent<Image>();
            btn.onClick.AddListener(SendCurrent);
            var btnText = UiFactory.CreateText("Text", btnRt, 24, TextAnchor.MiddleCenter);
            btnText.text = "发送";
            btnText.color = Color.white;
            UiFactory.Stretch(btnText.rectTransform, 0, 0, 0, 0);
        }
    }
}
