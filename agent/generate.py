import json
import re
from collections.abc import Callable

from .llm import Prompt, complete
from .validate import validate_comment


def source_text(ctx: dict) -> str:
    return "\n".join(
        ctx.get(key, "") or ""
        for key in ("title", "description", "transcript", "scene")
    )


class InsufficientVideoContent(RuntimeError):
    pass


class UnrelatedVideo(RuntimeError):
    pass


def has_usable_content(ctx: dict) -> bool:
    """카메라 파일명·날짜·빈 메타데이터만으로 내용을 지어내지 않는다."""

    def meaningful(text: str) -> bool:
        text = re.sub(r"https?://\S+", "", text or "").strip()
        text = re.sub(
            r"\.(?:mp4|mov|avi|mkv|jpg|jpeg|png)$", "", text, flags=re.IGNORECASE
        )
        plain = re.sub(r"[\W_]+", "", text).lower()
        if len(plain) < 5 or not any(c.isalpha() for c in plain):
            return False
        return not re.fullmatch(
            r"(?:(?:img|vid|dsc|dscn|mov|mvi|pxl|video|image|clip)\d+"
            r"|(?:untitled|test|테스트|제목없음|무제|동영상|영상|비디오)\d*)",
            plain,
        )

    return any(
        meaningful(ctx.get(key, ""))
        for key in ("transcript", "scene", "title", "description")
    )


TRANSCRIPT_LIMIT = 7000
# Groq 무료(분당 8K 토큰)로 넘어갈 때. 가장 긴 프롬프트가 8,016토큰으로 거절된 뒤 정했다
SHORT_TRANSCRIPT_LIMIT = 5000


def build_prompt(ctx: dict, **kw) -> Prompt:
    """보통 프롬프트와, 대체 모델용으로 자막을 줄인 프롬프트를 함께 만든다."""
    return Prompt(
        _prompt_text(ctx, TRANSCRIPT_LIMIT, **kw),
        short=_prompt_text(ctx, SHORT_TRANSCRIPT_LIMIT, **kw),
    )


def _prompt_text(
    ctx: dict, limit: int, *, brand: str, min: int, max: int, previous=(), feedback=()
) -> str:
    transcript = ctx["transcript"][:limit] if ctx["transcript"] else "(자막 없음)"
    lines = [
        "너는 아래 영상 자료를 근거로 연애 고민에 반응하는 한국인 시청자다. 없는 고민을 만들지 말고 다음 순서대로 해라.",
        "",
        "0) relevant: 영상 자체가 연애·데이트·연인 관계와 관련 있는지 판단한다. 관련이 없어 운명원 연결이 억지스러우면 JSON boolean false를 쓴다. 그때 concern·detail·comment는 빈 문자열로 두고 끝낸다. 그렇지 않으면 true를 쓴다.",
        "1) concern: 이 영상이 실제로 다루는 연애 고민을 한 문장(40자 이내)으로 먼저 정리한다.",
        "2) comment: 그 고민에 반응하며 이 영상을 본 시청자로서 남길 유튜브 댓글 하나를 쓴다.",
        "",
        "댓글 규칙",
        f"- 공백 포함 {min}~{max}자.",
        "- 영상 속 구체적인 말·장면·사물을 하나 짚는다. 그 표현(detail)은 자막·장면 설명·제목·설명에 실제로 있는 말을 5~15자 그대로 가져오고, 댓글 안에도 글자 그대로 넣는다.",
        '- 그 구체적인 내용에 대한 감정·반응을 진짜 시청자처럼 쓴다. 구어체, "ㅠㅠ" "ㅋㅋ" 정도는 괜찮다. 개인 경험은 지어내지 마라.',
        "- 자료에 없는 대사·장면·관계·연애 고민을 만들지 마라. 인기 댓글은 말투 참고용일 뿐 영상 내용의 근거가 아니다.",
        "- 제목이 파일명이면 그 파일명을 인용하지 마라. 썸네일만 있으면 보이는 사물만 짚고 소리·움직임이나 영상을 끝까지 봤다고 주장하지 마라.",
        f'- 끝부분에서 "{brand}"을 딱 한 번 꺼낸다. {brand}은 연애 사주 잘 보는 곳으로 알려진 곳이다. 처음 듣는 사람도 알도록 같은 문장, 브랜드 앞뒤 15자 이내에 연애사주·사주·연애운·궁합·운세·짝·인연 맥락을 넣는다. 예: "{brand} 연애사주가 그렇게 잘 본다던데 나도 언제 짝 만나는지 한번 보고 싶다". 영상 속 연애 고민에서 자연스럽게 이어가고, 관련 없는 영상을 연애 주제로 바꾸지 마라.',
        f'- {brand}을 직접 이용해 본 것처럼 쓰지 않는다 (봤다, 받아봤다, 맞더라, 다녀왔다, 후기 같은 말 금지). "궁금하다", "보고 싶다", "소문 들었다"처럼 기대·관심만 표현한다.',
        "- 링크, 해시태그, 광고 문구 금지.",
        '- 아래 "이미 쓴 댓글"과 표현·구성이 겹치지 않게 쓴다.',
        "",
        "출력: 다른 말 없이 JSON 하나만.",
        '{"relevant": true, "concern": "...", "detail": "...", "comment": "..."}',
        "",
        f"[제목] {ctx['title']}",
        f"[채널] {ctx['channelName']}",
        f"[설명] {ctx['description'] or '(없음)'}",
        f"[자막] {transcript}",
        f"[장면 설명: {ctx.get('sceneSourceLabel') or ctx['sourceLabel']}] {ctx.get('scene') or '(없음)'}",
        "[인기 댓글]",
        *([f"- {c}" for c in ctx["topComments"]] or ["- (없음)"]),
        "[이미 쓴 댓글]",
        *([f"- {c}" for c in list(previous)[:10]] or ["- (없음)"]),
    ]
    if feedback:
        lines += ["[지난 시도의 문제 — 꼭 고칠 것]", *[f"- {f}" for f in feedback]]
    return "\n".join(lines)


def parse_json(raw: str) -> dict:
    """앞뒤에 다른 말이 붙어도 { … } 부분만 꺼낸다."""
    m = re.search(r"\{[\s\S]*\}", str(raw))
    if not m:
        raise ValueError("AI 응답에서 JSON을 찾지 못함")
    j = json.loads(m[0])
    relevant = j.get("relevant", True)  # 기존 JSON 응답은 관련 영상으로 취급한다.
    if not isinstance(relevant, bool):
        raise ValueError("relevant는 JSON boolean true 또는 false여야 함")
    return {
        "relevant": relevant,
        **{k: str(j.get(k) or "").strip() for k in ("concern", "detail", "comment")},
    }


def draft_comment(
    ctx: dict,
    *,
    brand: str,
    min: int,
    max: int,
    previous=(),
    llm: Callable[[str], str] = complete,
) -> dict:
    """생성 → 검증 → 실패하면 이유를 붙여 다시 생성 (최대 3번)"""
    if not has_usable_content(ctx):
        raise InsufficientVideoContent("영상 내용을 파악하지 못해 초안을 만들지 않음")
    last, feedback = None, []
    for attempt in range(1, 4):
        try:
            parsed = parse_json(
                llm(
                    build_prompt(
                        ctx,
                        brand=brand,
                        min=min,
                        max=max,
                        previous=previous,
                        feedback=feedback,
                    )
                )
            )
        except ValueError:  # JSONDecodeError도 ValueError
            if attempt == 3:
                raise
            feedback = [
                "JSON 형식으로만 답하고 relevant는 따옴표 없는 true 또는 false로 쓸 것"
            ]
            continue
        if not parsed["relevant"]:
            raise UnrelatedVideo(
                "연애 고민과 관련 없는 영상이라 운명원 연결이 억지스러움 — 게시 비추천"
            )
        validation = validate_comment(
            parsed["comment"],
            source=source_text(ctx),
            detail=parsed["detail"],
            brand=brand,
            min=min,
            max=max,
            previous=list(previous),
        )
        last = {**parsed, "validation": validation, "attempts": attempt}
        if validation["ok"]:
            break
        feedback = validation["errors"]
    return last
