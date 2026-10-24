from types import SimpleNamespace

import pytest

from agent import generate
from agent.generate import build_prompt, register_match, select_candidates
from agent.validate import validate_comment
from agent.voice_examples import GOLD_IDS, VOICE_EXAMPLES, examples_for
from scripts import measure_gold_effort, prepare_gold_holdout
from tests.test_generate import CTX, RULES, candidate_json


@pytest.mark.parametrize(
    "example", VOICE_EXAMPLES, ids=lambda example: example["videoId"]
)
def test_승인_예시는_근거가_있으면_기존_검사를_모두_통과(example):
    result = validate_comment(
        example["comment"], source=example["detail"], detail=example["detail"], **RULES
    )
    assert result["ok"], result["errors"]


@pytest.mark.parametrize(
    "example", VOICE_EXAMPLES, ids=lambda example: example["videoId"]
)
def test_같은_영상의_승인답을_프롬프트에_넣지_않음(example):
    prompt = build_prompt({**CTX, "videoId": example["videoId"]}, **RULES)
    assert example["comment"] not in prompt
    assert len(examples_for(example["videoId"])) == 4
    for reference in examples_for(example["videoId"]):
        assert reference["comment"] in prompt
    assert "60~100자" in prompt and "존댓말" in prompt and "여러분" in prompt


def test_존댓말_어미와_웃음_뒤_어미를_세되_필요는_아님():
    assert register_match("남네요. 보세요! 좋습니다. 맞아요ㅋㅋ")["polite_endings"] == 4
    assert register_match("그게 필요. 중요한 게 중요.")["polite_endings"] == 0
    assert register_match("여러분은 어떤가요?")["counseling"] == 1
    assert register_match("가" * 103)["length_excess"] == 3


def test_통과_후보는_반복보다_반말과_100자_이하_우선(monkeypatch):
    comments = [
        "제 얘기 같네요. 운명원 궁합 궁금함",
        "나도 그런 중. 운명원 궁합 궁금함",
        "가" * 103,
        "저도 그렇습니다. 운명원 궁합 궁금함",
    ]
    monkeypatch.setattr(
        generate,
        "validate_comment",
        lambda text, **kw: {"ok": True, "errors": [], "chars": len(text)},
    )
    monkeypatch.setattr(
        generate,
        "diversity",
        lambda text, *a: {"score": 0.9 if text == comments[1] else 0.0, "overall": 0.0},
    )
    candidates = generate.parse_candidates(
        candidate_json({"detail": "연락 빈도부터 줄", "comment": "임시"})
    )
    for item, comment in zip(candidates, comments):
        item["comment"] = comment
    assert select_candidates(candidates, CTX, **RULES)["selected_index"] == 1
    assert (
        select_candidates(candidates, CTX, **RULES, prefer_register=False)[
            "selected_index"
        ]
        == 0
    )
    monkeypatch.setattr(
        generate,
        "validate_comment",
        lambda text, **kw: {
            "ok": text == comments[0],
            "errors": [] if text == comments[0] else ["실패"],
            "chars": len(text),
        },
    )
    assert (
        select_candidates(candidates, CTX, **RULES)["selected_index"] == 0
    )  # never weaken hard rules


def test_여러분_상담사_말투는_거절():
    text = VOICE_EXAMPLES[0]["comment"].replace("할 말 없어짐", "여러분 어떠신가요")
    result = validate_comment(text, source="혼자 서운해", detail="혼자 서운해", **RULES)
    assert not next(
        check for check in result["checks"] if check["key"] == "counseling"
    )["ok"]


def test_홀드아웃_준비는_승인영상과_무자막을_제외():
    cached = [
        {**CTX, "videoId": video_id, "channelId": "allowed", "description": "연애 설명"}
        for video_id in prepare_gold_holdout.CACHED_IDS
    ]
    channel = SimpleNamespace(id="allowed", name="채널")
    calls = []

    def fetch(video_id, **kw):
        calls.append((video_id, kw))
        return {
            **CTX,
            "videoId": video_id,
            "channelId": "allowed",
            "description": "연애 설명",
            "transcript": "" if video_id == "empty" else "연애에 대한 자막",
        }

    feed = lambda *a, **kw: [
        {"videoId": next(iter(GOLD_IDS))},
        {"videoId": "empty"},
        {"videoId": "fresh"},
    ]
    contexts, events = prepare_gold_holdout.prepare(
        SimpleNamespace(channels=[channel]),
        cached,
        fetch=fetch,
        feed=feed,
        fresh_limit=1,
    )
    assert [ctx["videoId"] for ctx in contexts] == [
        *prepare_gold_holdout.CACHED_IDS,
        "fresh",
    ]
    assert calls == [
        ("empty", {"include_scene": False}),
        ("fresh", {"include_scene": False}),
    ]
    assert any(event.get("result") == "no-transcript" for event in events)


def test_추론수준_측정은_동일프롬프트와_실패수로_선택(monkeypatch):
    from agent.llm import reasoning_effort

    calls = []

    def llm(prompt):
        calls.append((str(prompt), reasoning_effort()))
        text = (
            "반응. 운명원 궁합 궁금함"
            if reasoning_effort() == "medium"
            else "반응? 운명원 궁합 궁금함?"
        )
        return candidate_json({"detail": "연락 빈도부터 줄", "comment": text})

    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    result = measure_gold_effort.measure(
        [{**CTX, "videoId": "holdout"}], SimpleNamespace(**RULES), llm=llm, delay=0
    )
    assert calls[0][0] == calls[1][0]
    assert result["failed_candidates"] == {"low": 4, "medium": 0}
    assert result["chosen_effort"] == "medium"
    assert reasoning_effort() == "low"
    good = lambda _: candidate_json(
        {"detail": "연락 빈도부터 줄", "comment": "반응. 운명원 궁합 궁금함"}
    )
    assert (
        measure_gold_effort.measure(
            [{**CTX, "videoId": "holdout"}], SimpleNamespace(**RULES), llm=good, delay=0
        )["chosen_effort"]
        == "low"
    )
