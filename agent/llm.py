"""프롬프트 하나를 보내고 글을 받는다.

LLM_PROVIDER로 고른다: claude | codex | gemini | groq | openrouter.
비어 있으면 키가 있는 곳 → claude CLI 순서로 고르고, 둘 다 없으면 Gemini(무료 키 안내).
"""

import base64
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

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
# Gemini는 실제 영상 11건 비교에서 통과율이 같고 가장 빨라 3.5 Flash를 쓴다 (docs/IMPLEMENTATION.md 4장).
OPENAI_COMPATIBLE = {
    "gemini": Provider(
        "Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        "https://aistudio.google.com/apikey",
        "gemini-3.5-flash",
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
PROVIDERS = ("claude", "codex", *OPENAI_COMPATIBLE)
CODEX_MODEL = "gpt-6-luna"
CODEX_EFFORT = "low"
CODEX_TIMEOUT = 180

# Gemini 무료 한도(하루 20회)가 차거나 서버가 붐비면 Groq로 넘긴다.
# Groq 무료는 분당 8K 토큰이라 자막을 줄인 프롬프트(Prompt.short)를 보낸다.
FALLBACK_FROM, FALLBACK_TO = "gemini", "groq"
FALLBACK_STATUS = (429, 503)


class Prompt(str):
    """프롬프트 글. short에는 토큰 한도가 작은 대체 모델용으로 줄인 글을 담는다."""

    def __new__(cls, text: str, short: str | None = None):
        obj = super().__new__(cls, text)
        obj.short = short or text
        return obj


class ProviderError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


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
    if name == "codex":
        return f"Codex CLI · {_model(CODEX_MODEL)} · {CODEX_EFFORT}"
    if name == "claude":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return f"Claude API · {_model('claude-sonnet-5-5')}"
        return "claude CLI"
    p = OPENAI_COMPATIBLE[name]
    label = f"{p.name} · {_model(p.model)}"
    if _has_fallback(name):
        f = OPENAI_COMPATIBLE[FALLBACK_TO]
        label += f" (한도 초과 시 {f.name} · {f.model})"
    return label


def _has_fallback(name: str) -> bool:
    return name == FALLBACK_FROM and bool(
        os.environ.get(OPENAI_COMPATIBLE[FALLBACK_TO].key_env)
    )


def complete(prompt: str) -> str:
    name = provider_name()
    if name == "codex":
        return _codex_cli(prompt)
    if name == "claude":
        if key := os.environ.get("ANTHROPIC_API_KEY"):
            return _claude_api(prompt, key)
        return _claude_cli(prompt)
    p = OPENAI_COMPATIBLE[name]
    try:
        return _openai_compatible(p, prompt, _model(p.model))
    except ProviderError as e:
        if e.status not in FALLBACK_STATUS or not _has_fallback(name):
            raise
        f = OPENAI_COMPATIBLE[FALLBACK_TO]
        short = getattr(prompt, "short", prompt)
        try:
            # LLM_MODEL은 Gemini용이라 대체할 때는 Groq 기본 모델을 쓴다
            return _openai_compatible(f, short, f.model)
        except RuntimeError as e2:
            raise RuntimeError(f"{e} / 대체 {e2}") from e2


def media_available(*, video: bool = False) -> bool:
    """영상은 Gemini, 이미지는 Gemini 또는 선택된 Claude API로 읽는다."""
    if os.environ.get("GEMINI_API_KEY"):
        return True
    return (
        not video
        and provider_name() == "claude"
        and bool(os.environ.get("ANTHROPIC_API_KEY"))
    )


def complete_media(prompt: str, media: list[tuple[str, bytes]]) -> str:
    """작은 영상·이미지용 호출. 텍스트 complete의 공급자·대체 정책은 바꾸지 않는다."""
    if not media or any(
        mime not in {"video/mp4", "image/jpeg", "image/png"} for mime, _ in media
    ):
        raise ValueError("지원하지 않는 영상·이미지 형식")
    encoded = [(mime, base64.b64encode(raw).decode("ascii")) for mime, raw in media]
    p = OPENAI_COMPATIBLE["gemini"]
    if key := os.environ.get(p.key_env):
        # LLM_MODEL은 텍스트 공급자용일 수 있으므로 Gemini 기본 모델을 쓴다.
        data = _post(
            p,
            f"https://generativelanguage.googleapis.com/v1beta/models/{p.model}:generateContent",
            {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": prompt},
                            *[
                                {"inline_data": {"mime_type": mime, "data": raw}}
                                for mime, raw in encoded
                            ],
                        ],
                    }
                ]
            },
            {"x-goog-api-key": key},
        )
        try:
            text = "".join(
                part.get("text", "")
                for part in data["candidates"][0]["content"]["parts"]
            )
            return _text(p, text)
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("Gemini 영상·이미지 응답 형식이 예상과 다름") from e
    if any(mime == "video/mp4" for mime, _ in media) or not media_available():
        raise RuntimeError("영상·이미지를 읽을 수 있는 API 키가 없음")
    # Gemini 키가 없을 때만, 이미 선택된 Claude API로 이미지를 읽는다.
    p = Provider("Claude", "", "ANTHROPIC_API_KEY", "", "claude-sonnet-5-5")
    data = _post(
        p,
        "https://api.anthropic.com/v1/messages",
        {
            "model": _model("claude-sonnet-5-5"),
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        *[
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime,
                                    "data": raw,
                                },
                            }
                            for mime, raw in encoded
                        ],
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        },
        {
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
        },
    )
    return _text(
        p,
        "".join(b["text"] for b in data.get("content", []) if b.get("type") == "text"),
    )


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
        raise ProviderError(
            f"{p.name} 오류 {res.status_code}: {msg or res.text[:200]}{hint}",
            res.status_code,
        )
    return data


def _text(p: Provider, content) -> str:
    if not content:
        raise RuntimeError(f"{p.name}가 빈 답을 돌려줌")
    return content


def _openai_compatible(p: Provider, prompt: str, model: str) -> str:
    key = os.environ.get(p.key_env)
    if not key:
        raise RuntimeError(
            f"{p.name}: .env에 {p.key_env}가 없음. 무료 키는 {p.key_url}에서 받는다"
        )
    data = _post(
        p,
        f"{p.base_url}/chat/completions",
        {"model": model, "messages": [{"role": "user", "content": str(prompt)}]},
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
            "max_tokens": 4096,  # 댓글 후보 네 개의 JSON 응답 여유
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
            check=False,
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


def _codex_cli(prompt: str) -> str:
    """도구 없는 임시 작업 폴더에서 실행하고 -o의 최종 답만 읽는다."""
    with tempfile.TemporaryDirectory(prefix="yt-codex-") as directory:
        output = Path(directory) / "answer.txt"
        cmd = [
            os.environ.get("CODEX_CLI", "codex"),
            "exec",
            "-m",
            _model(CODEX_MODEL),
            "-c",
            f'model_reasoning_effort="{CODEX_EFFORT}"',
            "-c",
            "project_doc_max_bytes=0",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-rules",
            "-C",
            directory,
        ]
        for feature in (
            "shell_tool",
            "unified_exec",
            "multi_agent",
            "multi_agent_v2",
            "apps",
            "plugins",
            "remote_plugin",
            "browser_use",
            "computer_use",
            "image_generation",
            "skill_search",
        ):
            cmd += ["--disable", feature]
        cmd += ["-o", str(output), "-"]
        try:
            result = subprocess.run(
                cmd,
                input=str(prompt),
                capture_output=True,
                text=True,
                cwd=directory,
                timeout=CODEX_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Codex CLI 시간 초과 ({CODEX_TIMEOUT}초)") from error
        except OSError as error:
            raise RuntimeError(
                "Codex CLI 실행 실패: CODEX_CLI 경로와 설치 상태를 확인하세요"
            ) from error
        if result.returncode != 0:
            # stderr에는 지침·추론·인증 정보가 섞일 수 있어 전문을 노출하지 않는다.
            message = result.stderr.lower()
            if any(
                word in message
                for word in (
                    "unauthorized",
                    "authentication",
                    "not logged in",
                    "sign in",
                    "401",
                )
            ):
                reason = "인증 실패 — codex login 상태를 확인하세요"
            elif any(
                word in message
                for word in ("quota", "usage limit", "rate limit", "429")
            ):
                reason = "사용 한도 초과 — Codex 계정의 한도와 재시도 시각을 확인하세요"
            else:
                reason = "실행 실패 — 실행 파일·모델·연결 상태를 확인하세요"
            raise RuntimeError(f"Codex CLI {reason} (종료 코드 {result.returncode})")
        try:
            answer = output.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RuntimeError("Codex CLI 최종 답변 파일을 읽지 못함") from error
        if not answer:
            raise RuntimeError("Codex CLI가 빈 답을 돌려줌")
        return answer
