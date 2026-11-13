"""用真实浏览器（Edge + CDP）提交海外潜客官网联系表单。

为什么用浏览器而不是 requests：
- 多数建站平台（Wix / Squarespace / Webflow / Framer）的表单由前端 JS 提交，
  真实端点藏在打包后的 JS 里，逐个反查成本高且易错。
- 浏览器能自动处理 cookie、CSRF、token 和 JS 校验。
- reCAPTCHA v3 由页面自己加载并执行。

产出：每次提交落盘 evidence/<公司>.json，含时间、URL、HTTP 状态、响应片段、
以及页面上的成功/失败提示文本（用于人工复核是否真的送达）。
"""
import json
import os
import re
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = r"<project>"
EVID = os.path.join(BASE, "evidence")
CDP_PORT = 9337  # 回退值：浏览器用固定端口启动时用
EDGE_PROFILE = str(Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "browser-profile" / "edge")


def _port_from_profile(profile):
    """Edge 用 --remote-debugging-port=0 启动时端口是随机的，
    真实端口写在 profile 根目录的 DevToolsActivePort 里。
    写死 9337 会在浏览器重启/换端口后全线瘫痪（连接被拒）。"""
    try:
        p = os.path.join(profile, "DevToolsActivePort")
        with open(p, encoding="utf-8", errors="replace") as f:
            m = re.search(r"(\d+)", f.read(64))
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def cdp_port():
    """返回当前可用的 CDP 端口：先试 DevToolsActivePort，再试回退端口。"""
    p = _port_from_profile(EDGE_PROFILE)
    if p:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/json/version", timeout=3):
                return p
        except Exception:
            pass
    for cand in (CDP_PORT, 9222, 9223):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{cand}/json/version", timeout=2):
                return cand
        except Exception:
            continue
    raise RuntimeError(
        "找不到可用的 CDP 端口：Edge 调试端口已变且回退端口也不通。"
        "用 EdgeProfile 目录下的 DevToolsActivePort 确认真实端口。"
    )


class Page:
    """一个浏览器 tab 的最小封装。"""

    def __init__(self, ws_url):
        import websocket
        self.ws = websocket.create_connection(ws_url, timeout=40, max_size=60 * 1024 * 1024)
        self.id = 0
        self.pending = {}
        self.lock = threading.Lock()
        self.events = []
        self.reader_errors = []
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("Page.enable")
        self.send("Runtime.enable")
        self.send("Network.enable")

    def _log_error(self, msg, keep=50):
        # 错误日志必须有上界：连接抖动时会持续刷，撑爆内存。
        self.reader_errors.append(msg)
        if len(self.reader_errors) > keep:
            del self.reader_errors[:-keep]

    def _reader(self):
        # 注意：不能「一遇异常就 break」——CDP 偶发的大帧/解码错误会永久停掉
        # 事件收集，之后所有网络请求都收不到（表现为「提交成功但抓不到 POST」）。
        # 但连接真正关闭时必须退出线程，否则线程泄漏 + 错误日志无限增长。
        import websocket
        while True:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketConnectionClosedException:
                self._log_error("CONNECTION_CLOSED")
                break
            except Exception as e:
                self._log_error(f"{type(e).__name__}: {str(e)[:120]}")
                time.sleep(0.25)
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                self._log_error("JSON_DECODE_FAIL")
                continue
            if msg.get("method"):
                self.events.append(msg)
            else:
                i = msg.get("id")
                if i is not None:
                    with self.lock:
                        self.pending[i] = msg

    def send(self, method, params=None, timeout=25):
        self.id += 1
        i = self.id
        self.ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.lock:
                m = self.pending.pop(i, None)
            if m is not None:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            time.sleep(0.01)
        raise TimeoutError(method)

    def js(self, expr, await_promise=False, timeout=25):
        r = self.send("Runtime.evaluate",
                      {"expression": expr, "awaitPromise": await_promise,
                       "returnByValue": True}, timeout=timeout)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"])[:300])
        return r["result"].get("value")

    def goto(self, url, timeout=30, wait=4):
        self.send("Page.navigate", {"url": url}, timeout=timeout)
        time.sleep(wait)

    def click(self, x, y):
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
        time.sleep(0.35)
        self.send("Input.dispatchMouseEvent",
                  {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
        time.sleep(0.14)
        self.send("Input.dispatchMouseEvent",
                  {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def new_tab(port=None, url="about:blank"):
    """port=None 时自动发现当前 CDP 端口（浏览器换端口后不会全线瘫痪）。"""
    if port is None:
        port = cdp_port()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(url, safe='')}",
                                 method="PUT")
    with urllib.request.urlopen(req, timeout=10) as r:
        tab = json.loads(r.read())
    return Page(tab["webSocketDebuggerUrl"]), tab["id"]


import urllib.parse  # noqa: E402  (new_tab 用)
from pathlib import Path


def save_evidence(name, data):
    os.makedirs(EVID, exist_ok=True)
    p = os.path.join(EVID, name.replace(" ", "_").replace("/", "_") + ".json")
    data["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return p
