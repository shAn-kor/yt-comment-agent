"""Blind comparison orchestration uses fake LLM/network dependencies."""

import ast
import json
import subprocess
from types import SimpleNamespace

import pytest

from agent.llm import ProviderError
from scripts import compare_voice as comparison
from tests.test_generate import CTX, RULES, candidate_json
from tests.test_validate import GOOD


def generation_response(prompt, payload):
    return json.dumps(payload) if str(prompt) == "OLD" else candidate_json(payload)


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


@pytest.mark.parametrize(
    "revision,file,names",
    [
        ("b53e4f7", "voice_baseline.py", ("build_prompt", "_prompt_text")),
        ("50a3cf1", "shapes_baseline.py", ("build_prompt", "_prompt_text")),
        (
            "5a88e9a",
            "bridge_baseline.py",
            ("build_prompt", "_prompt_text", "voice_comments"),
        ),
    ],
)
def test_동결한_프롬프트_함수는_고정_커밋과_동일(revision, file, names):
    try:
        original = subprocess.check_output(
            ["git", "show", f"{revision}:agent/generate.py"],
            cwd=comparison.ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        pytest.skip("고정 커밋이 없는 얕은 복제에서는 동결본만 사용")
    frozen = (comparison.ROOT / "scripts" / file).read_text()
    for name in names:
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
    assert "3) bridge" in prompt and "4) comment" in prompt and "70~110자" in prompt
    assert "다섯 흐름을 순서대로" in prompt and "후보 4개" not in prompt
    assert comparison.BASE_REVISION == "50a3cf1"
    archive = comparison.baseline_builder("b53e4f7")(CTX, **RULES)
    assert "2) comment" in archive and "잘 본다던데" in archive


def test_비교는_각_버전_한번씩만_생성하고_버전은_key에만_저장(tmp_path):
    calls, old_histories = [], []

    def old_builder(*a, **kw):
        old_histories.append(list(kw["previous"]))
        return "OLD"

    def llm(prompt):
        calls.append(str(prompt))
        text = GOOD + " 잘 본다던데" if str(prompt) == "OLD" else GOOD
        return generation_response(
            prompt,
            {
                "relevant": True,
                "stance": "한줄요약",
                "detail": "연락 빈도부터 줄",
                "comment": text,
            },
        )

    result = comparison.compare(
        [context(), context("allowedVid2")],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=old_builder,
        llm=llm,
        seed=123,
    )
    assert len(calls) == 4 and not result["stop_reason"]
    assert calls.count("OLD") == 2
    assert old_histories == [[], [GOOD + " 잘 본다던데"]]
    new_prompts = [p for p in calls if p != "OLD"]
    assert GOOD in new_prompts[-1] and GOOD + " 잘 본다던데" not in new_prompts[-1]
    for index, row in enumerate(result["rows"]):
        assert sorted(row["labels"].values()) == ["new", "old"]
        assert row["reference"] == {"text": "높은 반응", "likes": 30}
        assert not row["drafts"]["old"]["validation"]["ok"]
        assert row["drafts"]["new"]["validation"]["ok"] is (index == 0)
        assert row["drafts"]["new"]["previous_count"] == index
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
        llm=lambda prompt: generation_response(
            prompt, {"detail": "연락 빈도부터 줄", "comment": GOOD}
        ),
        seed=1,
        delay=65,
        sleep=waits.append,
        baseline_revision="b53e4f7",
    )
    assert waits == [65] and old_comments == ["가" * 200]
    assert not result["stop_reason"]


def test_5a_기준은_좋아요와_잘리지_않은_원본_댓글을_동일하게_받음(tmp_path):
    comments = [{"text": "가" * 500, "likes": 20}]
    seen = []

    def old_builder(ctx, **kw):
        seen.append(ctx["topComments"])
        return "OLD"

    comparison.compare(
        [{**context(), "topComments": comments}],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=old_builder,
        llm=lambda prompt: generation_response(
            prompt, {"detail": "연락 빈도부터 줄", "comment": GOOD}
        ),
    )
    assert seen == [comments]


def test_한도_초과면_부분_결과를_저장하고_추가_호출_중단(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    calls = []

    def llm(prompt):
        calls.append(prompt)
        raise ProviderError("daily quota 429 secret-value", 429)

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
    "message", ["429 tokens per minute TPM quota", "503 service busy"]
)
def test_분당_한도와_혼잡은_실패로_기록하되_나머지_슬롯_계속(message, tmp_path):
    calls = []

    def llm(prompt):
        calls.append(prompt)
        raise ProviderError(message, 429 if "429" in message else 503)

    result = comparison.compare(
        [context(), context("allowedVid2")],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
    )
    assert len(calls) == 4 and not result["stop_reason"]
    assert all(d.get("error") for row in result["rows"] for d in row["drafts"].values())


def test_빈_응답만_한번_재요청하고_공급자_모델_이력_보존(tmp_path):
    calls, waits = [], []

    def llm(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("Groq가 빈 답을 돌려줌")
        return generation_response(
            prompt, {"detail": "연락 빈도부터 줄", "comment": GOOD}
        )

    result = comparison.compare(
        [context()],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
        provider="groq",
        model="openai/gpt-oss-120b",
        delay=65,
        sleep=waits.append,
    )
    drafts = list(result["rows"][0]["drafts"].values())
    assert len(calls) == 3 and waits == [65, 65]
    assert sorted(d["attempts"] for d in drafts) == [1, 2]
    assert sum(len(d["error_history"]) for d in drafts) == 1
    assert all(
        d["provider"] == "groq"
        and d["model"] == "openai/gpt-oss-120b"
        and d["prompt_variant"] == "short"
        for d in drafts
    )


def test_빈_응답이_계속되면_슬롯당_두번에서_멈춤(tmp_path):
    calls = []

    def llm(prompt):
        calls.append(prompt)
        return ""

    result = comparison.compare(
        [context()],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
    )
    assert len(calls) == 4 and not result["stop_reason"]
    assert all(
        d["attempts"] == 2 and d["error"] for d in result["rows"][0]["drafts"].values()
    )


def test_Groq는_짧은_프롬프트를_보냄(tmp_path):
    prompts = []

    def llm(prompt):
        prompts.append(str(prompt))
        return generation_response(
            prompt, {"detail": "연락 빈도부터 줄", "comment": GOOD}
        )

    comparison.compare(
        [{**context(), "transcript": "가" * 6000}],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
        provider="groq",
        model="openai/gpt-oss-120b",
    )
    [new_prompt] = [p for p in prompts if p != "OLD"]
    assert "가" * 5000 in new_prompt and "가" * 5001 not in new_prompt


def test_Codex_단발_비교는_전체_프롬프트와_선택결과_메타데이터_보존(tmp_path):
    prompts = []

    def llm(prompt):
        prompts.append(str(prompt))
        return generation_response(
            prompt, {"detail": "연락 빈도부터 줄", "comment": GOOD}
        )

    result = comparison.compare(
        [{**context(), "transcript": "가" * 6000}],
        SimpleNamespace(**RULES),
        tmp_path,
        old_builder=lambda *a, **k: "OLD",
        llm=llm,
        provider="codex",
        model="gpt-6-luna",
        transport="cli",
        effort="low",
        cli_path="/fake/codex",
        empty_retries=0,
    )
    [new_prompt] = [p for p in prompts if p != "OLD"]
    assert "가" * 6000 in new_prompt
    drafts = result["rows"][0]["drafts"]
    assert (
        drafts["old"]["candidate_count"] == 1 and drafts["new"]["candidate_count"] == 4
    )
    assert len(drafts["new"]["candidates"]) == 4
    assert len(prompts) == 2
    assert all(
        d["provider"] == "codex"
        and d["model"] == "gpt-6-luna"
        and d["effort"] == "low"
        and d["transport"] == "cli"
        and d["prompt_variant"] == "full"
        and d["transcript_chars_sent"] == 6000
        and d["attempts"] == 1
        for d in drafts.values()
    )


def test_Codex_전용_옵션은_다른_공급자로_실행하지_않음(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "load_env", lambda: None)
    monkeypatch.setattr(comparison, "load_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        comparison, "configured_model", lambda: ("claude", "other-model")
    )
    monkeypatch.setattr(
        comparison,
        "select_contexts",
        lambda *a: pytest.fail("잘못된 전송 경로에서는 요청 금지"),
    )
    assert comparison.main(["--require-codex-cli", "--output", str(tmp_path)]) == 1


def test_Codex_설정은_다른_API키와_무관하고_기본모델_유지(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-key")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert comparison.configured_model() == ("codex", "gpt-6-luna")


def test_공급자_모델_고정과_자동_대체_금지(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    with pytest.raises(ValueError, match="공급자가 섞이지"):
        comparison.configured_model()
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    assert comparison.configured_model() == ("groq", "openai/gpt-oss-120b")


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
    monkeypatch.setattr(comparison, "configured_model", lambda: ("fake", "test-model"))
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
