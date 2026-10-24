"""Codex provider tests run a local fake executable, never a model or API."""

import json
import sys
from pathlib import Path

import pytest

from agent import llm


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    executable = tmp_path / "fake-codex"
    trace = tmp_path / "trace.json"
    executable.write_text(
        f"#!{sys.executable}\n"
        + r"""
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
Path(os.environ["FAKE_CODEX_TRACE"]).write_text(json.dumps({"args": args, "cwd": os.getcwd(), "stdin": prompt}))
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
if mode == "sleep":
    time.sleep(5)
if mode == "exit":
    print("authentication failed token=DO_NOT_LEAK", file=sys.stderr)
    raise SystemExit(3)
if mode != "missing":
    output = Path(args[args.index("-o") + 1])
    output.write_text("  " if mode == "empty" else "최종 답변")
print("stdout must not be used as the final answer")
print("diagnostic stderr must not be returned", file=sys.stderr)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("CODEX_CLI", str(executable))
    monkeypatch.setenv("FAKE_CODEX_TRACE", str(trace))
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.setattr(
        llm.httpx,
        "post",
        lambda *a, **kw: pytest.fail("Codex mode must not use a paid/API provider"),
    )
    return trace


def test_Codex_기본_모델과_저비용_추론_설정(fake_codex):
    assert llm.provider_name() == "codex"
    assert llm.backend_name() == "Codex CLI · gpt-6-luna · low"
    assert llm.complete("후보 네 개를 써라") == "최종 답변"
    trace = json.loads(fake_codex.read_text())
    args = trace["args"]
    assert args[0] == "exec" and args[-1] == "-"
    assert args[args.index("-m") + 1] == "gpt-6-luna"
    assert 'model_reasoning_effort="low"' in args
    assert "project_doc_max_bytes=0" in args
    assert "--ignore-user-config" in args and "--ignore-rules" in args
    assert "--ephemeral" in args and "--skip-git-repo-check" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert Path(args[args.index("-C") + 1]).resolve() == Path(trace["cwd"])
    assert trace["stdin"] == "후보 네 개를 써라"
    assert "multi_agent" in args and "shell_tool" in args and "browser_use" in args
    assert not Path(trace["cwd"]).exists()  # final answer and cwd cleaned


def test_Codex_medium_추론은_실제_CLI_인수에_전달(fake_codex, monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "medium")
    llm.complete("글")
    assert (
        'model_reasoning_effort="medium"' in json.loads(fake_codex.read_text())["args"]
    )
    assert llm.backend_name().endswith("medium")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    with pytest.raises(RuntimeError, match="low 또는 medium"):
        llm.complete("글")


def test_Codex_명시적_모델_값은_유지(fake_codex, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-6-luna-test")
    llm.complete("글")
    args = json.loads(fake_codex.read_text())["args"]
    assert args[args.index("-m") + 1] == "gpt-6-luna-test"


@pytest.mark.parametrize(
    "mode,message",
    [("exit", "인증 실패"), ("empty", "빈 답"), ("missing", "최종 답변 파일")],
)
def test_Codex_실패를_한글로_알리고_임시파일_정리(
    fake_codex, monkeypatch, mode, message
):
    monkeypatch.setenv("FAKE_CODEX_MODE", mode)
    with pytest.raises(RuntimeError, match=message) as error:
        llm.complete("글")
    assert "DO_NOT_LEAK" not in str(error.value)
    assert not Path(json.loads(fake_codex.read_text())["cwd"]).exists()


def test_Codex_시간_초과(fake_codex, monkeypatch):
    monkeypatch.setenv("FAKE_CODEX_MODE", "sleep")
    monkeypatch.setattr(llm, "CODEX_TIMEOUT", 0.15)
    with pytest.raises(RuntimeError, match="Codex CLI 시간 초과"):
        llm.complete("글")
    if fake_codex.exists():
        assert not Path(json.loads(fake_codex.read_text())["cwd"]).exists()


def test_Codex_실행파일_없으면_명확한_오류(fake_codex, monkeypatch):
    monkeypatch.setenv("CODEX_CLI", "/nonexistent/codex")
    with pytest.raises(RuntimeError, match="CODEX_CLI 경로"):
        llm.complete("글")
