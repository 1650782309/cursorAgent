using System;
using System.Collections.Generic;
using UnityEngine;

namespace DesktopCompanion.Core
{
    /// <summary>
    /// 把后台线程（HTTP 流式回调）产生的动作切回 Unity 主线程执行。
    /// Unity 的 API 不是线程安全的，LLM 流式 onDelta 在后台线程触发，
    /// 更新 UI / 角色时必须通过本调度器。
    /// </summary>
    public class MainThreadDispatcher : MonoBehaviour
    {
        private static MainThreadDispatcher _instance;
        private readonly Queue<Action> _queue = new Queue<Action>();

        public static MainThreadDispatcher Instance
        {
            get
            {
                if (_instance == null)
                {
                    var go = new GameObject("MainThreadDispatcher");
                    _instance = go.AddComponent<MainThreadDispatcher>();
                    DontDestroyOnLoad(go);
                }
                return _instance;
            }
        }

        /// <summary>在主线程排队执行一个动作。</summary>
        public void Enqueue(Action action)
        {
            if (action == null) return;
            lock (_queue) _queue.Enqueue(action);
        }

        private void Update()
        {
            while (true)
            {
                Action action;
                lock (_queue)
                {
                    if (_queue.Count == 0) break;
                    action = _queue.Dequeue();
                }
                try { action(); }
                catch (Exception e) { Debug.LogException(e); }
            }
        }
    }
}
