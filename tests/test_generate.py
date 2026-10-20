import json

from agent.generate import build_prompt, draft_comment, parse_json
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
