# -*- coding: utf-8 -*-
"""通过 OpenCode 调大模型(2026-11-08 新建;不改 cost_layers/llm.py)。模型名写成 "oc:<模型>",例如 oc:gemini-4-argon、oc:deepseek-v4.1-flash。

密钥:~/.config/opencode/api_key(每次调用现读)。默认走 Go 订阅的接口(扣 Go 额度);OPENCODE_PLAN=zen 时走按量付费接口。
OpenCode 要求客户端带自己的 User-Agent 和稳定的会话编号(x-opencode-session)。
install():把 exp_sweep.supervise.ask_vision 换成分发版 —— oc: 开头的模型走这里,其余照旧(意图审计、L2 看图都经过它)。
SPEND:本进程累计的调用次数、token 与 OpenCode 报的标价(list_cost,美元)。
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path

import requests

KEY_FILE = Path("~/.config/opencode/api_key").expanduser()
SESSION = str(uuid.uuid4())
SPEND = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "list_cost": 0.0, "errors": 0}


def _url() -> str:
    return ("https://opencode.ai/inference/openai/v1/chat/completions" if os.environ.get("OPENCODE_PLAN", "go") == "zen"
            else "https://opencode.ai/inference/go/openai/v1/chat/completions")


def _post(model: str, messages: list, timeout_s: float, temperature: float = 0.2) -> dict:
    key = KEY_FILE.read_text().strip()
    H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "franka-cost-layers-exp/0.1",
         "x-opencode-session": SESSION}
    body = {"model": model, "messages": messages, "temperature": temperature}
    err = None
    for attempt in range(4):
        try:
            r = requests.post(_url(), headers=H, json=body, timeout=timeout_s)
        except Exception as e:                                                # noqa: BLE001  超时 / 断网:退避重试
            err = f"{type(e).__name__}: {e}"
            time.sleep(2 ** attempt * 2); continue
        if r.status_code in (429, 500, 502, 503, 504):
            err = f"HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(2 ** attempt * 3); continue
        if r.status_code != 200:
            SPEND["errors"] += 1
            return {"text": "", "error": f"HTTP {r.status_code}: {r.text[:300]}", "usage": {}}
        j = r.json()
        u = j.get("usage", {}) or {}
        SPEND["calls"] += 1
        SPEND["prompt_tokens"] += int(u.get("prompt_tokens", 0) or 0)
        SPEND["completion_tokens"] += int(u.get("completion_tokens", 0) or 0)
        SPEND["reasoning_tokens"] += int((u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0)
        SPEND["list_cost"] += float((u.get("opencode") or {}).get("list_cost", 0.0) or 0.0)
        try:
            text = j["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError):
            return {"text": "", "error": "返回里没有文本", "usage": u}
        return {"text": text.strip(), "error": None, "usage": u}
    SPEND["errors"] += 1
    return {"text": "", "error": err or "重试用完", "usage": {}}


def _parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[a:b + 1]) if a >= 0 and b > a else None
        except json.JSONDecodeError:
            return None


class OpenCodeChat:
    """和 cost_layers.llm 的客户端同一个接口:ask(system, user) -> {"text", "error", "usage"}。"""

    def __init__(self, model: str, timeout_s: float = 180.0, temperature: float = 0.2):
        self.model, self.timeout_s, self.temperature = model, timeout_s, temperature

    def ask(self, system: str, user: str) -> dict:
        return _post(self.model, [{"role": "system", "content": system}, {"role": "user", "content": user}], self.timeout_s, self.temperature)


def ask_vision_oc(model: str, system: str, user: str, images: list, timeout_s: float = 240.0) -> dict:
    """同 exp_sweep.supervise.ask_vision 的返回格式:{"text", "json", "error"}。images 是 PNG 字节。"""
    content = [{"type": "text", "text": user}] + [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b).decode()}}
                                                  for b in images]
    r = _post(model, [{"role": "system", "content": system}, {"role": "user", "content": content}], timeout_s)
    return {"text": r["text"], "json": _parse_json(r["text"]) if r["text"] else None, "error": r["error"], "usage": r["usage"]}


def make_llm_any(model: str, **kw):
    """oc: 开头走 OpenCode,其余交给 cost_layers.llm.make_llm。"""
    if model.startswith("oc:"):
        return OpenCodeChat(model[3:], timeout_s=kw.get("timeout_s") or 180.0)
    from cost_layers.llm import make_llm
    return make_llm(model, **kw)


def install() -> None:
    """让 exp_sweep.supervise 里所有看图调用(意图审计、L2)认得 oc: 模型。"""
    import exp_sweep.supervise as S
    if getattr(S.ask_vision, "_oc", False):
        return
    orig = S.ask_vision

    def dispatch(model, system, user, images, timeout_s=120.0):
        if model.startswith("oc:"):
            return ask_vision_oc(model[3:], system, user, images, timeout_s=max(timeout_s, 120.0))
        return orig(model, system, user, images, timeout_s=timeout_s)
    dispatch._oc = True
    S.ask_vision = dispatch
