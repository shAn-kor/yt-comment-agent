"""프롬프트 하나를 보내고 글을 받는다. 키가 있으면 Claude API, 없으면 로컬 claude CLI."""

import os
import subprocess
import tempfile

import httpx


def backend_name() -> str:
    return "Claude API" if os.environ.get("ANTHROPIC_API_KEY") else "claude CLI"


def complete(prompt: str) -> str:
    model = os.environ.get("LLM_MODEL", "")
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        res = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": model or "claude-sonnet-5-5",
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
