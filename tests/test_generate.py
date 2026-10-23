import json

import pytest

from agent.generate import (
    InsufficientVideoContent,
    UnrelatedVideo,
    build_prompt,
    draft_comment,
    parse_json,
    source_text,
)
from tests.test_validate import GOOD, SOURCE

CTX = {
    "title": "남자가 연락을 줄이는 진짜 이유",
    "description": "",
    "transcript": SOURCE,
    "sourceLabel": "자막",
    "channelName": "테스트",
    "topComments": [],
}
RULES = dict(brand="운명원", min=40, max=120)


def test_AI_응답_JSON_파싱():
    j = parse_json('설명 {"concern":"고민","detail":"말","comment":"댓글"} 끝')
    assert j == {
        "relevant": True,
        "stance": "",
        "bridge": "",
        "concern": "고민",
        "detail": "말",
        "comment": "댓글",
    }


@pytest.mark.parametrize("relevant", [True, False])
def test_relevant는_JSON_boolean_그대로_유지(relevant):
    assert parse_json(json.dumps({"relevant": relevant}))["relevant"] is relevant


@pytest.mark.parametrize("relevant", ["false", 0, None, []])
def test_relevant가_boolean이_아니면_거절(relevant):
    with pytest.raises(ValueError, match="JSON boolean"):
        parse_json(json.dumps({"relevant": relevant}))


def test_연애와_무관하면_검증과_재시도_없이_중단(monkeypatch):
    ctx = {
        **CTX,
        "title": "IMG 0978",
        "transcript": "",
        "scene": "흰 강아지가 풀밭을 걷는다.",
    }
    calls = []

    def fake_llm(prompt):
        calls.append(prompt)
        return json.dumps(
            {"relevant": False, "concern": "", "detail": "", "comment": ""}
        )

    monkeypatch.setattr(
        "agent.generate.validate_comment",
        lambda *a, **k: pytest.fail("무관한 영상 검증 금지"),
    )
    with pytest.raises(UnrelatedVideo, match="연애 고민과 관련 없는 영상.*게시 비추천"):
        draft_comment(ctx, **RULES, llm=fake_llm)
    assert len(calls) == 1


def test_relevant가_빠진_기존_응답은_생성_허용():
    draft = draft_comment(
        CTX,
        **RULES,
        llm=lambda _: json.dumps(
            {
                "concern": "연락 고민",
                "detail": "연락 빈도부터 줄",
                "comment": GOOD,
            }
        ),
    )
    assert draft["relevant"] is True and draft["validation"]["ok"]


def test_검증_실패_시_이유를_붙여_다시_생성():
    prompts = []
    answers = [
        json.dumps({"concern": "연락 고민", "detail": "없는 말", "comment": "짧음"}),
        json.dumps(
            {"concern": "연락 고민", "detail": "연락 빈도부터 줄", "comment": GOOD}
        ),
    ]

    def fake_llm(p):
        prompts.append(p)
        return answers[len(prompts) - 1]

    draft = draft_comment(CTX, **RULES, llm=fake_llm)
    assert draft["attempts"] == 2
    assert draft["validation"]["ok"]
    assert "지난 시도의 문제" in prompts[1]
    assert "운명원" in build_prompt(CTX, **RULES)


def test_브랜드_맥락_없으면_구체적인_안내로_재생성():
    prompts = []
    without_context = GOOD.replace(
        "운명원에서 내 인연은 언제 오는지 궁금하다",
        "운명원도 궁금해지네요",
    )

    def fake_llm(prompt):
        prompts.append(prompt)
        return json.dumps(
            {
                "relevant": True,
                "concern": "연락 고민",
                "detail": "연락 빈도부터 줄",
                "comment": without_context if len(prompts) == 1 else GOOD,
            }
        )

    draft = draft_comment(CTX, **RULES, llm=fake_llm)
    assert draft["attempts"] == 2 and draft["validation"]["ok"]
    assert "앞선 40자 이내" in prompts[1]


def test_relevant가_문자열이면_boolean_안내로_다시_요청():
    prompts = []

    def fake_llm(prompt):
        prompts.append(prompt)
        return json.dumps(
            {
                "relevant": "false" if len(prompts) == 1 else True,
                "concern": "연락 고민",
                "detail": "연락 빈도부터 줄",
                "comment": GOOD,
            }
        )

    draft = draft_comment(CTX, **RULES, llm=fake_llm)
    assert draft["attempts"] == 2 and draft["validation"]["ok"]
    assert "relevant는 따옴표 없는 true 또는 false" in prompts[1]


def test_JSON이_아니면_다시_요청():
    answers = iter(
        [
            "죄송합니다",
            json.dumps({"concern": "c", "detail": "연락 빈도부터 줄", "comment": GOOD}),
        ]
    )
    draft = draft_comment(CTX, **RULES, llm=lambda p: next(answers))
    assert draft["attempts"] == 2


def test_대체_모델용_프롬프트는_자막을_줄임():
    ctx = {**CTX, "transcript": "가" * 6000 + "끝부분"}
    p = build_prompt(ctx, **RULES)
    assert "가" * 6000 + "끝부분" in p
    assert "가" * 5000 in p.short and "가" * 5001 not in p.short
    assert p.short.replace("가" * 5000, "") == p.replace("가" * 6000 + "끝부분", "")


def test_프롬프트는_연애_관련성_확인_후_고민을_먼저_정리():
    ctx = {
        **CTX,
        "title": "IMG 0978",
        "transcript": "",
        "scene": "흰 강아지가 풀밭을 걷는다.",
    }
    prompt = build_prompt(ctx, **RULES)
    assert "다루는 연애 고민" in prompt
    assert (
        prompt.index("0) relevant")
        < prompt.index("1) concern")
        < prompt.index("2) stance")
        < prompt.index("3) bridge")
        < prompt.index("4) comment")
    )
    assert "연애·데이트·연인 관계" in prompt and "false" in prompt
    assert "운명원이란 곳이 괜찮아 보이던데" in prompt and ctx["scene"] in prompt
    assert "70~110자" in prompt and "역설·자기고백" in prompt
    assert "브랜드 없이 연애사주·궁합" in prompt and "다른 시청자에게 질문" in prompt
    assert "연결이 어렵다는 이유로 거절하지 말고" in prompt
    assert "고정된 마지막 문장을 만들지 마라" in prompt
    assert "따옴표로 감싸지 마라" in prompt and "기본적으로 생략" in prompt
    assert '"relevant": true' in prompt
    assert "제목과 설명만 사용" not in prompt
    assert "자료에 없는 대사·장면·관계·연애 고민을 만들지 마라" in prompt


def test_인기_댓글은_좋아요순_말투_참고이며_홍보와_링크는_제외():
    ctx = {
        **CTX,
        "topComments": [
            {"text": "두 번째 반응", "likes": 12},
            {"text": "제 채널 놀러 오세요", "likes": 999},
            {"text": "최고 반응", "likes": 35},
            {"text": "무료 상담 문의", "likes": 999},
            {"text": "내용 " * 90 + "https://example.com", "likes": 999},
            {"text": "전각 ｈｔｔｐｓ://example.com", "likes": 999},
            {"text": "운명원 궁합 보고 싶어요", "likes": 999},
            "예전 형식 댓글",
        ],
    }
    prompt = build_prompt(ctx, **RULES)
    assert prompt.index("좋아요 35개: 최고 반응") < prompt.index(
        "좋아요 12개: 두 번째 반응"
    )
    assert "좋아요 0개: 예전 형식 댓글" in prompt
    assert "말투 참고만" in prompt
    for removed in (
        "제 채널 놀러",
        "무료 상담 문의",
        "example.com",
        "운명원 궁합 보고 싶어요",
    ):
        assert removed not in prompt


def test_선택한_입장은_JSON에_보존():
    parsed = parse_json('{"stance":"반박·비틀기","comment":"내용"}')
    assert parsed["stance"] == "반박·비틀기"
    assert (
        parse_json('{"bridge":"이 사람을 기다려도 될까?"}')["bridge"]
        == "이 사람을 기다려도 될까?"
    )
    assert parse_json('{"stance":"자기고백"}')["stance"] == "자기고백"


def test_장면_설명도_detail_검사_근거():
    ctx = {
        **CTX,
        "title": "IMG 0978",
        "transcript": "",
        "scene": "서로 손을 잡고 걷던 연인이 연락이 줄어 불안하다고 말한다.",
    }
    assert ctx["scene"] in source_text(ctx)
    draft = draft_comment(
        ctx,
        **RULES,
        llm=lambda _: json.dumps(
            {
                "relevant": True,
                "concern": "연인의 연락이 줄어 불안한 고민",
                "detail": "서로 손을 잡고",
                "comment": "서로 손을 잡고 걷는데도 나만 불안한가 싶네요. 내 인연은 어떨지 운명원 연애사주도 궁금해지네요.",
            }
        ),
    )
    assert draft["validation"]["ok"] and draft["attempts"] == 1


@pytest.mark.parametrize(
    "title,description",
    [
        ("IMG 0978", ""),
        ("VID_20261022_120000.mp4", ""),
        ("", ""),
        ("2026-10-22", ""),
        ("테스트", ""),
        ("Untitled", "https://example.com"),
    ],
)
def test_내용_없으면_LLM_호출_전에_차단(title, description):
    ctx = {
        **CTX,
        "title": title,
        "description": description,
        "transcript": "",
        "scene": "",
    }

    def forbidden(_):
        pytest.fail("내용 없는 영상은 AI로 보내면 안 됨")

    with pytest.raises(InsufficientVideoContent, match="영상 내용을 파악하지 못해"):
        draft_comment(ctx, **RULES, llm=forbidden)


def test_구체적인_설명만_있으면_생성_허용():
    ctx = {**CTX, "title": "IMG 0978", "description": SOURCE, "transcript": ""}
    draft = draft_comment(
        ctx,
        **RULES,
        llm=lambda _: json.dumps(
            {
                "concern": "연락 고민",
                "detail": "연락 빈도부터 줄",
                "comment": GOOD,
            }
        ),
    )
    assert draft["validation"]["ok"]
