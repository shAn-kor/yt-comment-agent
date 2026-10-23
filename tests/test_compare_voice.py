"""Blind comparison orchestration uses fake LLM/network dependencies."""

import ast
import json
import subprocess
from types import SimpleNamespace

import pytest

from agent.llm import ProviderError
from scripts import compare_voice as comparison
from tests.test_generate import CTX, RULES
from tests.test_validate import GOOD


def context(video_id="allowedVid1"):
    return {
        **CTX,
        "videoId": video_id,
        "channelId": "channel-a",
        "topComments": [
            {"text": "낮은 반응", "likes": 2},
            {"text": "높은 반응", "likes": 30},
        ],
    }


def test_동결한_프롬프트_함수는_고정_커밋과_동일():
    try:
        original = subprocess.check_output(
            ["git", "show", f"{comparison.BASE_REVISION}:agent/generate.py"],
            cwd=comparison.ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        pytest.skip("고정 커밋이 없는 얕은 복제에서는 동결본만 사용")
    frozen = (comparison.ROOT / "scripts/voice_baseline.py").read_text()
    for name in ("build_prompt", "_prompt_text"):
        before = next(
            n
            for n in ast.parse(original).body
            if isinstance(n, ast.FunctionDef) and n.name == name
        )
        after = next(
            n
            for n in ast.parse(frozen).body
            if isinstance(n, ast.FunctionDef) and n.name == name
        )
        assert ast.dump(before) == ast.dump(after)


def test_이전_프롬프트는_동결본을_사용():
    prompt = comparison.baseline_builder()(CTX, **RULES)
    assert "2) comment" in prompt and "잘 본다던데" in prompt
    assert "2) stance" not in prompt


def test_비교는_각_버전_한번씩만_생성하고_버전은_key에만_저장(tmp_path):
    calls = []

    def llm(prompt):
        calls.append(str(prompt))
        text = GOOD + " 잘 본다던데" if str(prompt) == "OLD" else GOOD
        return json.dumps(
            {
                "relevant": True,
                "stance": "한줄요약",
                "detail": "연락 빈도부터 줄",
                "comment": text,
            }
        )

    result = comparison.compare(
        [context(), context("allowedVid2")],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
        seed=123,
    )
    assert len(calls) == 4 and not result["stop_reason"]
    assert calls.count("OLD") == 2
    for row in result["rows"]:
        assert sorted(row["labels"].values()) == ["new", "old"]
        assert row["reference"] == {"text": "높은 반응", "likes": 30}
        assert not row["drafts"]["old"]["validation"]["ok"]
        assert row["drafts"]["new"]["validation"]["ok"]
        assert row["drafts"]["new"]["chars"] == len(GOOD)
    sheet = (tmp_path / "sheet.md").read_text()
    assert "old" not in sheet and "new" not in sheet
    assert "높은 반응" in sheet and "### A" in sheet and "### B" in sheet
    assert "single-shot" in sheet and "재작성 루프는 사용하지 않았다" in sheet
    assert json.loads((tmp_path / "key.json").read_text())["seed"] == 123
    with pytest.raises(ValueError, match="이미 있음"):
        comparison.compare(
            [], SimpleNamespace(**RULES), tmp_path, old_builder=lambda *a, **k: "OLD"
        )


def test_호출_간격과_이전_댓글_200자_제한(tmp_path):
    waits, old_comments = [], []
    ctx = {**context(), "topComments": [{"text": "가" * 500, "likes": 10}]}

    def old_builder(ctx, **kw):
        old_comments.extend(ctx["topComments"])
        return "OLD"

    result = comparison.compare(
        [ctx],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=old_builder,
        llm=lambda _: json.dumps({"detail": "연락 빈도부터 줄", "comment": GOOD}),
        seed=1,
        delay=65,
        sleep=waits.append,
    )
    assert waits == [65] and old_comments == ["가" * 200]
    assert not result["stop_reason"]


def test_한도_초과면_부분_결과를_저장하고_추가_호출_중단(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    calls = []

    def llm(prompt):
        calls.append(prompt)
        raise ProviderError("quota 429 secret-value", 429)

    result = comparison.compare(
        [context(), context("allowedVid2")],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
        seed=2,
    )
    assert len(calls) == 1 and "429" in result["stop_reason"]
    assert "secret-value" not in (tmp_path / "key.json").read_text()
    assert "미생성" in (tmp_path / "sheet.md").read_text()


@pytest.mark.parametrize(
    "error,stop,expected", [(False, "", 0), (True, "", 1), (True, "quota 429", 2)]
)
def test_CLI는_일반_실패와_한도_실패를_종료_코드로_알림(
    error, stop, expected, tmp_path, monkeypatch
):
    monkeypatch.setattr(comparison, "load_env", lambda: None)
    monkeypatch.setattr(
        comparison,
        "load_config",
        lambda: SimpleNamespace(comment=SimpleNamespace(**RULES)),
    )
    monkeypatch.setattr(comparison, "select_contexts", lambda *a: [context()])
    monkeypatch.setattr(comparison, "attach_likes", lambda *a: None)
    monkeypatch.setattr(comparison, "backend_name", lambda: "fake")
    monkeypatch.setattr(
        comparison,
        "compare",
        lambda *a, **kw: {
            "stop_reason": stop,
            "rows": [{"drafts": {"old": {"error": "failed"} if error else {}}}],
        },
    )
    assert comparison.main(["--count", "1", "--output", str(tmp_path)]) == expected


def test_캐시도_설정_채널만_중복_없이_고름(tmp_path):
    cache = tmp_path / "contexts.json"
    cache.write_text(
        json.dumps(
            [
                context(),
                context(),
                {**context("allowedVid2"), "channelId": "other"},
                {**context("allowedVid3"), "channelId": "channel-b"},
            ]
        )
    )
    config = SimpleNamespace(
        channels=[SimpleNamespace(id="channel-a"), SimpleNamespace(id="channel-b")]
    )
    selected = comparison.select_contexts(config, 2, cache)
    assert [ctx["videoId"] for ctx in selected] == ["allowedVid1", "allowedVid3"]


@pytest.mark.parametrize("missing", ["transcript", "description"])
def test_불완전한_캐시는_앱의_영상자료_경로로_보완(missing, tmp_path, monkeypatch):
    cached = context()
    if missing == "transcript":
        cached.update(transcript=" ", scene="")
    else:
        cached.pop("description")
    file = tmp_path / "contexts.json"
    file.write_text(json.dumps([cached]))
    fetched = []

    def fetch(video_id):
        fetched.append(video_id)
        return {**context(video_id), "description": "실제 영상 설명"}

    monkeypatch.setattr(comparison, "get_video_context", fetch)
    config = SimpleNamespace(channels=[SimpleNamespace(id="channel-a")])
    [selected] = comparison.select_contexts(config, 1, file)
    assert fetched == ["allowedVid1"]
    assert selected["transcript"] and selected["description"] == "실제 영상 설명"


def test_자막_대신_장면_설명이_있는_캐시는_허용(tmp_path, monkeypatch):
    cached = {**context(), "transcript": "", "scene": "두 사람이 손을 잡고 걷는다."}
    file = tmp_path / "contexts.json"
    file.write_text(json.dumps([cached]))
    monkeypatch.setattr(
        comparison, "get_video_context", lambda _: pytest.fail("불필요한 재요청")
    )
    config = SimpleNamespace(channels=[SimpleNamespace(id="channel-a")])
    assert comparison.select_contexts(config, 1, file)[0]["scene"] == cached["scene"]


def test_다시_받아도_자막과_장면이_없으면_비교에_넣지_않음(tmp_path, monkeypatch):
    cached = {**context(), "transcript": "", "scene": ""}
    file = tmp_path / "contexts.json"
    file.write_text(json.dumps([cached]))
    monkeypatch.setattr(comparison, "get_video_context", lambda _: cached)
    config = SimpleNamespace(channels=[SimpleNamespace(id="channel-a")])
    with pytest.raises(ValueError, match="0개뿐"):
        comparison.select_contexts(config, 1, file)


def test_새_영상_컨텍스트는_요청한_수만_받음(monkeypatch):
    config = SimpleNamespace(
        channels=[SimpleNamespace(id="channel-a"), SimpleNamespace(id="channel-b")]
    )
    monkeypatch.setattr(
        comparison,
        "fetch_channel_feed",
        lambda channel, limit: [{"videoId": f"{channel.id}-{i}"} for i in range(limit)],
    )
    fetched = []

    def fetch(video_id):
        fetched.append(video_id)
        return {**context(video_id), "channelId": video_id.rsplit("-", 1)[0]}

    monkeypatch.setattr(comparison, "get_video_context", fetch)
    assert len(comparison.select_contexts(config, 3)) == 3
    assert len(fetched) == 3


def test_수집한_좋아요_수를_캐시에_붙임(tmp_path):
    file = tmp_path / "comments.jsonl"
    file.write_text(
        json.dumps(
            {"video_id": "allowedVid1", "text": "실제\u2028반응", "likes": 35},
            ensure_ascii=False,
        )
        + "\n\n"
    )
    contexts = [context()]
    comparison.attach_likes(contexts, file)
    assert contexts[0]["topComments"] == [{"text": "실제\u2028반응", "likes": 35}]
