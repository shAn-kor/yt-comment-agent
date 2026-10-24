import httpx
import pytest

from agent import llm

KEYS = ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in (*KEYS, "LLM_PROVIDER", "LLM_MODEL"):
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


def test_키도_CLI도_없으면_Gemini_키_안내(calls):
    assert llm.provider_name() == "gemini"
    assert llm.backend_name() == "Gemini · gemini-3.5-flash"
    with pytest.raises(RuntimeError, match="aistudio.google.com/apikey"):
        llm.complete("p")
    assert calls == []


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
    with pytest.raises(ValueError, match="가능: claude, codex, gemini"):
        llm.complete("p")
    assert llm.backend_name().startswith("설정 오류")


@pytest.mark.parametrize(
    "provider,key,url,model",
    [
        (
            "gemini",
            "GEMINI_API_KEY",
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            "gemini-3.5-flash",
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


@pytest.fixture
def replies(monkeypatch):
    """요청 주소마다 다른 답을 준다 (Gemini → Groq 대체 확인용)."""
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append({"url": url, "json": json})
        status, body = sent.by_host["groq" if "groq" in url else "gemini"]
        return httpx.Response(status, json=body)

    sent = type("Sent", (list,), {})()
    sent.by_host = {}
    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return sent


OK = (200, {"choices": [{"message": {"content": "답"}}]})


@pytest.mark.parametrize("status", [429, 503])
def test_Gemini_한도_초과면_Groq로_줄인_프롬프트(monkeypatch, replies, status):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    replies.by_host = {"gemini": (status, {"error": {"message": "quota"}}), "groq": OK}
    assert llm.complete(llm.Prompt("긴 글", short="짧은 글")) == "답"
    gemini, groq = replies
    assert gemini["json"]["messages"][0]["content"] == "긴 글"
    assert gemini["json"]["model"] == "gemini-3.8-flash"
    assert groq["json"]["messages"][0]["content"] == "짧은 글"
    assert groq["json"]["model"] == "openai/gpt-oss-120b"  # LLM_MODEL을 넘기지 않음
    assert llm.backend_name().endswith("(한도 초과 시 Groq · openai/gpt-oss-120b)")


def test_Groq_키가_없으면_대체하지_않음(monkeypatch, replies):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    replies.by_host = {"gemini": (429, {"error": {"message": "quota"}})}
    with pytest.raises(RuntimeError, match="Gemini 오류 429"):
        llm.complete("p")
    assert len(replies) == 1


def test_다른_오류는_대체하지_않음(monkeypatch, replies):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    replies.by_host = {"gemini": (400, {"error": {"message": "bad key"}}), "groq": OK}
    with pytest.raises(RuntimeError, match="bad key"):
        llm.complete("p")
    assert len(replies) == 1


def test_대체도_실패하면_두_오류를_함께_알림(monkeypatch, replies):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    replies.by_host = {
        "gemini": (429, {"error": {"message": "quota"}}),
        "groq": (413, {"error": {"message": "TPM Limit 8000"}}),
    }
    with pytest.raises(RuntimeError, match="Gemini 오류 429.*대체 Groq 오류 413"):
        llm.complete("p")  # 일반 글이면 short가 없으니 같은 글을 보낸다
    assert replies[1]["json"]["messages"][0]["content"] == "p"


def test_Gemini_네이티브_영상_요청은_기본_모델과_헤더_키(monkeypatch, calls):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_MODEL", "text-only-model")
    calls.reply = (200, {"candidates": [{"content": {"parts": [{"text": "장면"}]}}]})
    assert llm.media_available(video=True)
    assert llm.complete_media("보이는 내용", [("video/mp4", b"video")]) == "장면"
    req = calls[0]
    assert req["url"].endswith("/gemini-3.5-flash:generateContent")
    assert "secret" not in req["url"]
    assert req["headers"] == {"x-goog-api-key": "secret"}
    assert req["json"]["contents"][0]["parts"] == [
        {"text": "보이는 내용"},
        {"inline_data": {"mime_type": "video/mp4", "data": "dmlkZW8="}},
    ]


def test_이미지도_Gemini_네이티브로(monkeypatch, calls):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls.reply = (200, {"candidates": [{"content": {"parts": [{"text": "사진"}]}}]})
    assert llm.complete_media("p", [("image/jpeg", b"jpeg")]) == "사진"
    assert (
        calls[0]["json"]["contents"][0]["parts"][1]["inline_data"]["mime_type"]
        == "image/jpeg"
    )


def test_선택된_Claude_API는_이미지만_대체(monkeypatch, calls):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    calls.reply = (200, {"content": [{"type": "text", "text": "사진"}]})
    assert llm.media_available() and not llm.media_available(video=True)
    assert llm.complete_media("p", [("image/jpeg", b"jpeg")]) == "사진"
    req = calls[0]
    assert req["url"] == "https://api.anthropic.com/v1/messages"
    assert (
        req["json"]["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"
    )
    with pytest.raises(RuntimeError, match="API 키가 없음"):
        llm.complete_media("p", [("video/mp4", b"video")])
    assert len(calls) == 1


def test_멀티모달_키_없으면_호출하지_않음(calls):
    assert not llm.media_available()
    with pytest.raises(RuntimeError, match="API 키가 없음"):
        llm.complete_media("p", [("image/jpeg", b"jpeg")])
    assert calls == []


def test_영상_응답이_비었으면_오류(monkeypatch, calls):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls.reply = (200, {"candidates": []})
    with pytest.raises(RuntimeError, match="응답 형식"):
        llm.complete_media("p", [("video/mp4", b"video")])
