import httpx
import pytest

from agent import llm

KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (*KEYS, "LLM_PROVIDER", "LLM_MODEL", "OLLAMA_HOST", "OLLAMA_NUM_CTX"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm.shutil, "which", lambda _: None)  # claude CLI 없음


@pytest.fixture
def calls(monkeypatch):
    """httpx.post를 가로채 요청을 기록하고 정해 둔 답을 준다."""
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "headers": headers, "json": json})
        status, body = sent.reply
        return httpx.Response(status, json=body)

    sent = type("Sent", (list,), {})()
    sent.reply = (200, {"choices": [{"message": {"content": "답"}}]})
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return sent


def test_키도_CLI도_없으면_Ollama():
    assert llm.provider_name() == "ollama"
    assert llm.backend_name() == "Ollama · gemma4:12b"


def test_키가_있으면_그_공급자(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert llm.provider_name() == "groq"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")  # Claude 키가 먼저
    assert llm.provider_name() == "claude"


def test_키가_없고_claude_CLI가_있으면_CLI(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda _: "/usr/bin/claude")
    assert llm.provider_name() == "claude"
    assert llm.backend_name() == "claude CLI"


def test_LLM_PROVIDER가_우선(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("LLM_PROVIDER", "Gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-3.5-flash-lite")
    assert llm.provider_name() == "gemini"
    assert llm.backend_name() == "Gemini · gemini-3.5-flash-lite"


def test_이상한_LLM_PROVIDER는_오류(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt")
    with pytest.raises(ValueError, match="가능: claude, gemini"):
        llm.complete("p")
    assert llm.backend_name().startswith("설정 오류")


@pytest.mark.parametrize(
    "provider,key,url,model",
    [
        (
            "gemini",
            "GEMINI_API_KEY",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "gemini-3.8-flash",
        ),
        (
            "groq",
            "GROQ_API_KEY",
            "https://api.groq.com/openai/v1/chat/completions",
            "openai/gpt-oss-120b",
        ),
        (
            "openrouter",
            "OPENROUTER_API_KEY",
            "https://openrouter.ai/api/v1/chat/completions",
            "google/gemma-4-31b-it:free",
        ),
    ],
)
def test_OpenAI_호환_요청(monkeypatch, calls, provider, key, url, model):
    monkeypatch.setenv("LLM_PROVIDER", provider)
    monkeypatch.setenv(key, "secret")
    assert llm.complete("프롬프트") == "답"
    req = calls[0]
    assert req["url"] == url
    assert req["headers"]["Authorization"] == "Bearer secret"
    assert req["json"]["model"] == model
    assert req["json"]["messages"] == [{"role": "user", "content": "프롬프트"}]


def test_키가_없으면_알려줌(monkeypatch, calls):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY가 없음"):
        llm.complete("p")
    assert calls == []


def test_Ollama는_자체_API로_문맥_길이를_정함(monkeypatch, calls):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    calls.reply = (200, {"message": {"role": "assistant", "content": "로컬 답"}})
    assert llm.complete("p") == "로컬 답"
    req = calls[0]
    assert req["url"] == "http://127.0.0.1:11434/api/chat"
    assert req["json"]["stream"] is False
    assert req["json"]["options"]["num_ctx"] == 16384


def test_Ollama가_꺼져_있으면_안내(monkeypatch):
    def refuse(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(llm.httpx, "post", refuse)
    with pytest.raises(RuntimeError, match="ollama serve"):
        llm.complete("p")


def test_429는_무료_한도_안내(monkeypatch, calls):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")
    calls.reply = (429, {"error": {"message": "Rate limit reached"}})
    with pytest.raises(
        RuntimeError, match="Groq 오류 429: Rate limit reached.*무료 한도"
    ):
        llm.complete("p")


def test_Gemini_목록형_오류(monkeypatch, calls):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls.reply = (400, [{"error": {"message": "API key not valid"}}])
    with pytest.raises(RuntimeError, match="API key not valid"):
        llm.complete("p")


def test_빈_답은_오류(monkeypatch, calls):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    calls.reply = (200, {"choices": [{"message": {"content": None}}]})
    with pytest.raises(RuntimeError, match="빈 답"):
        llm.complete("p")
