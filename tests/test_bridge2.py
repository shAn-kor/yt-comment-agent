from types import SimpleNamespace

import pytest

from agent import generate
from agent.generate import parse_candidates, select_candidates
from agent.validate import plural_hearsay, validate_comment
from tests.test_generate import CTX, RULES, candidate_json

DETAIL = "연락 빈도부터 줄"
PREFIX = (
    "연락 빈도부터 줄인다는 말에 나도 기다릴 건가 싶음. 이 사람이랑 인연인지 궁금해짐. "
)


def checked(suffix, prefix=PREFIX):
    return validate_comment(prefix + suffix, source=DETAIL, detail=DETAIL, **RULES)


def check(result, key):
    return next(item for item in result["checks"] if item["key"] == key)


def test_최종표는_대시보드_피드백_경로를_사용(tmp_path):
    import json

    from scripts.generate_final import generate as generate_final

    prompts = []

    def llm(prompt):
        prompts.append(str(prompt))
        return candidate_json(
            {
                "detail": DETAIL,
                "comment": "운명원"
                if len(prompts) == 1
                else PREFIX + "주변에서 운명원 궁합 본 사람들 꽤 있던데",
            }
        )

    record = generate_final(
        [{**CTX, "videoId": "testvideo"}],
        SimpleNamespace(**RULES),
        tmp_path / "final",
        llm=llm,
        delay=0,
    )
    assert len(prompts) == 2 and "지난 시도의 문제" in prompts[1]
    assert record["rows"][0]["draft"]["attempts"] == 2
    assert record["rows"][0]["draft"]["validation"]["ok"]
    assert json.loads((tmp_path / "final/key.json").read_text())["llm_calls"] == 2
    assert "검사: 통과" in (tmp_path / "final/sheet.md").read_text()
    with pytest.raises(FileExistsError):
        generate_final(
            [], SimpleNamespace(**RULES), tmp_path / "final", llm=llm, delay=0
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "주변에서 운명원 궁합 봤다는 사람 몇 명 있던데",
        "주변에서 운명원 다녀왔다는 사람 여럿 있던데",
        "주변에서 운명원 궁합 보고 왔다는 사람 몇 명 있던데",
        "주변에서 운명원 연애사주 보러 간 사람 몇 명 있던데",
        "주변에서 운명원 궁합 본 사람들 꽤 있던데",
        "요즘 주변에서 운명원 연애사주 얘기 많이 하던데",
    ],
)
def test_복수_제삼자_전언은_직접이용으로_오인하지_않음(suffix):
    result = checked(suffix)
    assert plural_hearsay(suffix, "운명원")
    assert result["ok"], result["errors"]


@pytest.mark.parametrize("claim", ["봤는데", "받아봤음", "다녀왔어", "맞더라"])
def test_직접이용은_복수전언을_붙여도_거절(claim):
    result = checked(f"나는 운명원 궁합 {claim}, 주변에서 다녀왔다는 사람 여럿 있던데")
    assert not check(result, "fake")["ok"]


@pytest.mark.parametrize(
    "claim", ["맞췄대", "맞았대", "용하대", "잘 맞힌대", "소름", "후기", "추천"]
)
def test_효능은_복수_전언이어도_거절(claim):
    result = checked(f"주변에서 운명원 궁합 본 사람들 꽤 있던데 {claim}")
    assert not check(result, "fake")["ok"]


@pytest.mark.parametrize(
    "source", ["친구가", "친구한테", "언니가", "동생이", "지인이", "회사 동료가"]
)
def test_브랜드_문장의_단일_출처는_거절(source):
    assert not check(checked(f"{source} 운명원 연애사주 얘기 하던데"), "single_source")[
        "ok"
    ]


def test_브랜드_없는_앞문장의_친구_반응은_막지_않음():
    result = checked(
        "주변에서 운명원 궁합 본 사람들 꽤 있던데",
        prefix="친구가 연락 빈도부터 줄였다니 나도 기다릴 건가 싶음. 내 인연은 언제 오는지 궁금함. ",
    )
    assert check(result, "single_source")["ok"]


def test_지적_궁합질문은_내_바람을_대신하지_않음():
    result = checked(
        "이런 대화도 궁합에 영향을 주는지 운명원 연애사주가 궁금해짐",
        prefix="연락 빈도부터 줄인다는 말에 나도 멈칫함. ",
    )
    assert not check(result, "wish_bridge")["ok"]
    assert "풀리지 않은 바람" in check(result, "wish_bridge")["note"]


@pytest.mark.parametrize(
    "wish",
    [
        "내 인연",
        "언제",
        "잘 될지",
        "맞는 사람",
        "이 사람이랑",
        "궁합 문제",
        "타이밍",
        "다시 만날",
    ],
)
def test_결과_바람은_직전_또는_브랜드_문장에서_확인(wish):
    result = checked(
        "주변에서 운명원 연애사주 얘기 많이 하던데",
        prefix=f"연락 빈도부터 줄인다는 말에 나도 멈칫함. {wish} 궁금해짐. ",
    )
    assert check(result, "wish_bridge")["ok"]
    in_brand = checked(
        f"{wish} 궁금해서 주변에서 운명원 연애사주 얘기 많이 하던데",
        prefix="연락 빈도부터 줄인다는 말에 나도 멈칫함. ",
    )
    assert check(in_brand, "wish_bridge")["ok"]


@pytest.mark.parametrize("phrase", ["들어본", "들어 본", "알아본", "물어 본", "찾아본"])
def test_들은_적_있냐는_질문은_이용_전언이_아님(phrase):
    result = checked(f"운명원 연애사주 얘기는 {phrase} 사람?")
    assert not check(result, "hearsay")[
        "ok"
    ]  # an audience question alone is not social proof
    assert check(result, "fake")["ok"]


def test_먼_앞문장의_바람만으로는_부족():
    result = checked(
        "주변에서 운명원 연애사주 얘기 많이 하던데",
        prefix="내 인연은 언제 올지 궁금함. 연락 빈도부터 줄이는 말에 나도 멈칫함. ",
    )
    assert not check(result, "wish_bridge")["ok"]


def test_단수_사람_전언과_위장한_자기_이용은_거절():
    assert not check(checked("운명원 궁합 보고 왔다는 사람 한 명 있던데"), "hearsay")[
        "ok"
    ]
    assert not check(checked("내가 운명원 궁합 봤다는 사람 여럿 있던데"), "fake")["ok"]
    assert not check(
        checked(
            "운명원 궁합 궁금함",
            prefix="나도 사주 봤는데. 연락 빈도부터 줄이는 사람과 인연인지 궁금함. ",
        ),
        "fake",
    )["ok"]


def test_복수전언을_반복점수보다_우선하되_말투는_유지(monkeypatch):
    comments = [
        "내 인연 궁금해짐. 운명원 궁합 궁금함",
        "내 인연 궁금해짐. 주변에서 운명원 궁합 본 사람들 꽤 있던데",
        "내 인연 궁금하네요. 주변에서 운명원 궁합 본 사람들 꽤 있던데",
        "임시",
    ]
    monkeypatch.setattr(
        generate,
        "validate_comment",
        lambda text, **kw: {
            "ok": text != "임시",
            "errors": [] if text != "임시" else ["실패"],
            "chars": len(text),
        },
    )
    monkeypatch.setattr(
        generate,
        "diversity",
        lambda text, *a: {"score": 0.9 if text == comments[1] else 0.0, "overall": 0.0},
    )
    candidates = parse_candidates(candidate_json({"detail": DETAIL, "comment": "임시"}))
    for candidate, text in zip(candidates, comments):
        candidate["comment"] = text
    selected = select_candidates(candidates, CTX, **RULES)
    assert selected["selected_index"] == 1 and selected["plural_hearsay"]


@pytest.mark.parametrize("reaction", ["그게 나였네", "그게 되면 이 영상 안 봤지ㅋㅋ"])
def test_승인된_자기반응_형태도_인식(reaction):
    result = checked(
        "주변에서 운명원 궁합 본 사람들 꽤 있던데",
        prefix=f"연락 빈도부터 줄이라는데 {reaction}. 내 인연인지 궁금함. ",
    )
    assert check(result, "reaction")["ok"]
