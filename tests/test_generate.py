import json

import pytest

from agent.generate import (
    InsufficientVideoContent,
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
    assert j == {"concern": "고민", "detail": "말", "comment": "댓글"}


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


def test_프롬프트는_연애를_가정하지_않고_장면을_사용():
    ctx = {
        **CTX,
        "title": "IMG 0978",
        "transcript": "",
        "scene": "흰 강아지가 풀밭을 걷는다.",
    }
    prompt = build_prompt(ctx, **RULES)
    assert "연애 영상" not in prompt
    assert "다루는 연애 고민" not in prompt
    assert "영상 요지" in prompt and ctx["scene"] in prompt
    assert "제목과 설명만 사용" not in prompt


def test_장면_설명도_detail_검사_근거():
    ctx = {
        **CTX,
        "title": "IMG 0978",
        "transcript": "",
        "scene": "흰 강아지가 풀밭을 걷는다.",
    }
    assert ctx["scene"] in source_text(ctx)
    draft = draft_comment(
        ctx,
        **RULES,
        llm=lambda _: json.dumps(
            {
                "concern": "강아지 산책",
                "detail": "흰 강아지가 풀밭을",
                "comment": "흰 강아지가 풀밭을 걷는 모습이 편안하네요. 같이 걷는 짝꿍도 있으면 좋겠고 운명원도 궁금해지네요.",
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
