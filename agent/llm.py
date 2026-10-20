"""프롬프트 하나를 보내고 글을 받는다.

LLM_PROVIDER로 고른다: claude | gemini | groq | openrouter.
비어 있으면 키가 있는 곳 → claude CLI 순서로 고르고, 둘 다 없으면 Gemini(무료 키 안내).
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Provider:
    name: str  # 화면에 보일 이름
    base_url: str  # OpenAI 호환 주소 (끝의 /chat/completions 제외)
    key_env: str  # API 키 환경 변수
    key_url: str  # 키 발급 페이지
    model: str  # 기본 모델
    timeout: int = 120


# 무료 등급 기준 기본 모델. 2026-10-20 공식 문서로 확인.
OPENAI_COMPATIBLE = {
    "gemini": Provider(
        "Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "https://aistudio.google.com/apikey",
        "gemini-3.8-flash",
    ),
    "groq": Provider(
        "Groq",
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        "https://console.groq.com/keys",
        "openai/gpt-oss-120b",
    ),
    "openrouter": Provider(
        "OpenRouter",
        "https://openrouter.ai/api/v1",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/settings/keys",
        "google/gemma-4-31b-it:free",
    ),
}
PROVIDERS = ("claude", *OPENAI_COMPATIBLE)


def provider_name() -> str:
    """LLM_PROVIDER 값. 비어 있으면 쓸 수 있는 것을 고른다."""
    name = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if name:
        if name not in PROVIDERS:
            raise ValueError(
                f"LLM_PROVIDER 값이 이상함: {name} (가능: {', '.join(PROVIDERS)})"
            )
        return name
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    for key, p in OPENAI_COMPATIBLE.items():
        if os.environ.get(p.key_env):
            return key
    if shutil.which(os.environ.get("CLAUDE_CLI", "claude")):
        return "claude"
    return "gemini"  # 키도 claude CLI도 없으면 무료 키를 받으라고 안내


def _model(default: str) -> str:
    return os.environ.get("LLM_MODEL", "") or default


def backend_name() -> str:
    try:
        name = provider_name()
    except ValueError as e:
        return f"설정 오류 · {e}"
    if name == "claude":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return f"Claude API · {_model('claude-sonnet-5-5')}"
        return "claude CLI"
    p = OPENAI_COMPATIBLE[name]
    return f"{p.name} · {_model(p.model)}"


def complete(prompt: str) -> str:
    name = provider_name()
    if name == "claude":
        if key := os.environ.get("ANTHROPIC_API_KEY"):
            return _claude_api(prompt, key)
        return _claude_cli(prompt)
    return _openai_compatible(OPENAI_COMPATIBLE[name], prompt)


def _post(p: Provider, url: str, body: dict, headers: dict | None = None) -> dict:
    try:
        res = httpx.post(url, headers=headers or {}, json=body, timeout=p.timeout)
    except httpx.ConnectError as e:
        raise RuntimeError(f"{p.name} 연결 실패: {e}") from e
    except httpx.TimeoutException as e:
        raise RuntimeError(f"{p.name} 시간 초과 ({p.timeout}초)") from e
    try:
        data = res.json()
    except ValueError:
        data = {}
    if res.status_code != 200:
        if isinstance(data, list) and data:  # Gemini는 [{error: …}]로 줄 때가 있다
            data = data[0]
        err = data.get("error") if isinstance(data, dict) else None
        msg = err.get("message") if isinstance(err, dict) else err
        hint = (
            " (무료 한도 초과일 수 있음. 잠시 뒤 다시 시도)"
            if res.status_code == 429
            else ""
        )
        raise RuntimeError(
            f"{p.name} 오류 {res.status_code}: {msg or res.text[:200]}{hint}"
        )
    return data


def _text(p: Provider, content) -> str:
    if not content:
        raise RuntimeError(f"{p.name}가 빈 답을 돌려줌")
    return content


def _openai_compatible(p: Provider, prompt: str) -> str:
    key = os.environ.get(p.key_env)
    if not key:
        raise RuntimeError(
            f"{p.name}: .env에 {p.key_env}가 없음. 무료 키는 {p.key_url}에서 받는다"
        )
    data = _post(
        p,
        f"{p.base_url}/chat/completions",
        {"model": _model(p.model), "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": f"Bearer {key}"},
    )
    try:
        return _text(p, data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"{p.name} 응답 형식이 예상과 다름") from e


def _claude_api(prompt: str, key: str) -> str:
    res = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        json={
            "model": _model("claude-sonnet-5-5"),
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    data = res.json()
    if res.status_code != 200:
        raise RuntimeError(
            f"Claude API 오류: {data.get('error', {}).get('message') or res.status_code}"
        )
    return "".join(b["text"] for b in data["content"] if b["type"] == "text")


def _claude_cli(prompt: str) -> str:
    model = os.environ.get("LLM_MODEL", "")
    cmd = [os.environ.get("CLAUDE_CLI", "claude"), "-p", "--output-format", "text"] + (
        ["--model", model] if model else []
    )
    try:
        # 프로젝트 지침을 읽지 않도록 임시 폴더에서 실행
        out = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            timeout=180,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"claude CLI 실행 실패: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("claude CLI 시간 초과 (180초)") from e
    if out.returncode != 0:
        raise RuntimeError(f"claude CLI 오류 ({out.returncode}): {out.stderr[-300:]}")
    return out.stdout
