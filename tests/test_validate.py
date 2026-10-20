from agent.validate import count_chars, similarity, validate_comment

SOURCE = "남자가 연락을 줄이는 진짜 이유. 남자는 확신이 없으면 연락 빈도부터 줄입니다. 읽씹은 관심이 식었다는 신호일 수 있어요."
GOOD = (
    "확신이 없으면 연락 빈도부터 줄인다는 말 듣고 뜨끔했다ㅠㅠ 나도 맨날 혼자 기다리기만 했는데. "
    "운명원 연애사주가 그렇게 잘 본다던데 내 인연은 언제 오는지 궁금하다"
)
OPTS = dict(source=SOURCE, detail="연락 빈도부터 줄", brand="운명원", min=40, max=120)


def errors(text, **kw):
    return ", ".join(validate_comment(text, **{**OPTS, **kw})["errors"])


def test_조건을_다_지키면_통과():
    v = validate_comment(GOOD, **OPTS)
    assert v["ok"], v["errors"]
    assert v["anchor"]
    assert [c["key"] for c in v["checks"]] == [
        "length",
        "brand",
        "link",
        "fake",
        "anchor",
        "unique",
    ]


def test_글자_수_범위():
    assert "글자 수" in errors("운명원 궁금하다")
    assert "글자 수" in errors(GOOD + GOOD)
    assert count_chars("ㅠㅠ 가나") == 5


def test_브랜드는_정확히_한_번():
    assert "없음" in errors(GOOD.replace("운명원", "그곳"))
    assert "2번" in errors(GOOD.replace("궁금하다", "운명원 궁금하다"))


def test_링크와_해시태그_금지():
    assert "링크" in errors(GOOD.replace("궁금하다", "unmyeong.com 궁금"))
    assert "해시태그" in errors(GOOD.replace("궁금하다", "#연애사주"))


def test_운명원_이용_후기처럼_쓰면_차단():
    fake = GOOD.replace(
        "잘 본다던데 내 인연은 언제 오는지 궁금하다", "받아봤는데 진짜 소름 돋게 맞더라"
    )
    assert "이용해 본 것처럼" in errors(fake)


def test_브랜드_없는_문장의_봤는데는_허용():
    watched = GOOD.replace("말 듣고", "말 영상으로 봤는데")
    assert validate_comment(watched, **OPTS)["ok"], errors(watched)


def test_영상_속_표현이_없으면_차단():
    generic = "연애는 정말 어렵다ㅠㅠ 나만 이렇게 힘든가 싶어서 오늘도 한숨만 쉬었다. 운명원 연애사주 잘 본다던데 나도 언젠가 꼭 한번 보고 싶다"
    assert "장면" in errors(generic, detail="없는 말")


def test_이전_댓글과_비슷하면_차단():
    assert "비슷" in errors(GOOD, previous=[GOOD.replace("궁금하다", "궁금함")])
    assert similarity("가나다라", "마바사아") < 0.1


def test_강조할_부분은_원문_그대로():
    v = validate_comment(GOOD, **OPTS)
    assert v["anchor"] in GOOD
