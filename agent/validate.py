"""댓글 검증기. 생성된 초안과 사람이 고친 글 모두 게시 전에 여기를 통과해야 한다."""

import re
import unicodedata


def norm(s) -> str:
    """NFC로 맞추고 소문자로 바꾼 뒤 글자·숫자만 남긴다."""
    s = unicodedata.normalize("NFC", str(s or "")).lower()
    return "".join(c for c in s if c.isalnum())


def count_chars(s) -> int:
    return len(str(s or "").strip())


LINK = re.compile(
    r"(https?://|www\.|[a-z0-9-]+\.(com|net|org|kr|co|me|io|ly|gg|link|site|shop)\b)",
    re.I,
)
HASHTAG = re.compile(r"#[^\s#]")
# 브랜드를 직접 이용해 본 것처럼 읽히는 표현 (브랜드가 들어간 문장에서만 검사)
FAKE_USE = re.compile(
    r"(봤는데|봤더니|봤어요|봤음|봤다|받아\s?봤|받았는데|받았어|다녀왔|다녀옴|가\s?봤|상담\s?받|맞더라|맞았|맞추더|용하더|소름|후기)"
)


def _bigrams(s) -> set[str]:
    n = norm(s)
    return {n[i : i + 2] for i in range(len(n) - 1)}


def similarity(a, b) -> float:
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    inter = len(A & B)
    return inter / (len(A) + len(B) - inter)


def longest_common(a: str, b: str) -> str:
    """a의 부분 문자열 중 b에도 있는 가장 긴 것"""
    best = ""
    for i in range(len(a)):
        j = i + len(best) + 1
        while j <= len(a) and a[i:j] in b:
            best = a[i:j]
            j += 1
    return best


def _locate(text: str, normalized: str) -> str:
    """정규화된 조각을 원문에서 다시 찾는다 (공백·문장부호를 건너뛰며). 미리보기 강조용."""
    if not normalized:
        return ""
    pattern = r"[\W_]*".join(re.escape(c) for c in normalized)
    m = re.search(pattern, unicodedata.normalize("NFC", text), re.I)
    return m[0] if m else ""


def validate_comment(
    comment,
    *,
    source: str = "",
    detail: str = "",
    brand: str = "운명원",
    min: int = 40,
    max: int = 120,
    previous: list[str] | None = None,
) -> dict:
    """source: 자막·제목·설명을 합친 글. detail: 모델이 인용했다고 밝힌 영상 속 표현."""
    text = str(comment or "").strip()
    chars = count_chars(text)
    checks: list[dict] = []

    def add(key, label, ok, note=""):
        checks.append({"key": key, "label": label, "ok": bool(ok), "note": note})

    add(
        "length",
        f"{min}~{max}자",
        min <= chars <= max,
        f"글자 수 {chars}자 (기준 {min}~{max}자)",
    )

    n = text.count(brand)
    brand_note = (
        f'"{brand}"이(가) 없음'
        if n == 0
        else f'"{brand}"이(가) {n}번 나옴 (1번만)'
        if n > 1
        else ""
    )
    add("brand", f'"{brand}" 한 번', n == 1, brand_note)

    link, tag = bool(LINK.search(text)), bool(HASHTAG.search(text))
    add(
        "link",
        "링크·해시태그 없음",
        not link and not tag,
        ", ".join(x for x in [link and "링크 금지", tag and "해시태그 금지"] if x),
    )

    fake = next(
        (
            m
            for s in re.split(r"[.!?…\n]+", text)
            if brand in s and (m := FAKE_USE.search(s))
        ),
        None,
    )
    add(
        "fake",
        "이용 후기처럼 쓰지 않음",
        not fake,
        f'{brand}을(를) 이용해 본 것처럼 읽힘 ("{fake[0]}")' if fake else "",
    )

    # 영상 속 장면·말: 모델이 밝힌 인용구가 원문과 댓글 모두에 있거나, 원문과 6자 이상 겹쳐야 한다
    src = norm(source)
    body = norm(" ".join(text.split(brand)))
    d = norm(detail)
    anchor = ""
    if len(d) >= 3 and d in src and d in body:
        anchor = _locate(text, d) or detail
    else:
        common = longest_common(body, src)
        if len(common) >= 6:
            anchor = _locate(text, common) or common
    anchor_note = (
        "영상 자료가 없어 장면 확인 불가"
        if not src
        else ""
        if anchor
        else "영상 속 장면·말이 댓글에 없음"
    )
    add("anchor", "영상 속 장면·말 포함", src and anchor, anchor_note)

    dup = next((p for p in previous or [] if p and similarity(text, p) >= 0.5), None)
    add("unique", "이전 댓글과 다름", not dup, "이전 댓글과 너무 비슷함" if dup else "")

    errors = [c["note"] for c in checks if not c["ok"]]
    return {
        "ok": not errors,
        "errors": errors,
        "checks": checks,
        "chars": chars,
        "anchor": anchor,
    }
