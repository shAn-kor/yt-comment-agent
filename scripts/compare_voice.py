"""Compare one-shot old/new drafts on real configured-channel videos. Never posts.

uv run python scripts/compare_voice.py --count 8 --contexts /path/to/contexts.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx

from agent.config import load_config, load_env
from agent.generate import (
    SHORT_TRANSCRIPT_LIMIT,
    TRANSCRIPT_LIMIT,
    build_prompt,
    parse_candidates,
    parse_json,
    select_candidates,
    source_text,
    voice_comments,
)
from agent.llm import (
    CODEX_MODEL,
    OPENAI_COMPATIBLE,
    backend_name,
    complete,
    provider_name,
    reasoning_effort,
)
from agent.validate import validate_comment
from agent.voice_examples import GOLD_IDS
from agent.youtube import fetch_channel_feed, get_video_context
from scripts.bridge_baseline import build_prompt as bridge_baseline_prompt
from scripts.gold_baseline import build_prompt as gold_baseline_prompt
from scripts.shapes_baseline import build_prompt as shapes_baseline_prompt
from scripts.voice_baseline import build_prompt as original_baseline_prompt

BASE_REVISION = "f1c6e45"
BASELINES = {
    "b53e4f7": original_baseline_prompt,
    "5a88e9a": bridge_baseline_prompt,
    "50a3cf1": shapes_baseline_prompt,
    "f1c6e45": gold_baseline_prompt,
}
RESEARCH = Path.home() / "ai-workspace/scratch/comment-research"


def baseline_builder(revision=BASE_REVISION):
    """Use the frozen prompt, without its original generation/retry loop."""
    return BASELINES[revision]


def _has_video_material(ctx: dict) -> bool:
    return isinstance(ctx.get("description"), str) and any(
        isinstance(ctx.get(key), str) and ctx[key].strip()
        for key in ("transcript", "scene")
    )


def select_contexts(config, count: int, cache: Path | None = None) -> list[dict]:
    allowed = {channel.id for channel in config.channels}
    if cache is not None:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        groups = [
            [ctx for ctx in cached if ctx.get("channelId") == channel.id]
            for channel in config.channels
        ]
        candidates = [
            group[i]
            for i in range(max((len(g) for g in groups), default=0))
            for group in groups
            if i < len(group)
        ]
    else:
        feeds = [
            fetch_channel_feed(channel, limit=count) for channel in config.channels
        ]
        entries = [feed[i] for i in range(count) for feed in feeds if i < len(feed)][
            :count
        ]
        candidates = [get_video_context(entry["videoId"]) for entry in entries]
    selected, seen = [], set()
    for ctx in candidates:
        if ctx.get("channelId") not in allowed or ctx.get("videoId") in seen:
            continue
        seen.add(ctx["videoId"])
        if cache is not None and not _has_video_material(ctx):
            ctx = get_video_context(ctx["videoId"])
        if ctx.get("channelId") not in allowed or not _has_video_material(ctx):
            continue
        selected.append(dict(ctx))
        if len(selected) == count:
            break
    if len(selected) < count:
        raise ValueError(
            f"설정 채널의 실제 영상이 {len(selected)}개뿐임 (요청 {count}개)"
        )
    return selected


def attach_likes(contexts: list[dict], comments_file: Path | None) -> None:
    if comments_file is None or not comments_file.exists():
        return
    grouped = {}
    # JSON 문자열의 U+2028 등은 레코드 구분자가 아니다. 물리적인 줄만 나눈다.
    for line in comments_file.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        row = json.loads(line)
        grouped.setdefault(row["video_id"], []).append(
            {"text": row["text"], "likes": row.get("likes", 0)}
        )
    for ctx in contexts:
        if ctx["videoId"] in grouped:
            ctx["topComments"] = grouped[ctx["videoId"]]


def safe_error(error: Exception) -> str:
    text = str(error)
    for name, value in os.environ.items():
        if value and any(word in name for word in ("KEY", "TOKEN", "SECRET")):
            text = text.replace(value, "[REDACTED]")
    return f"{type(error).__name__}: {text}"


def configured_model() -> tuple[str, str]:
    name = provider_name()
    if name == "gemini" and os.environ.get("GROQ_API_KEY"):
        raise ValueError(
            "비교 중 공급자가 섞이지 않도록 자동 대체가 없는 공급자로 고정하세요 (예: LLM_PROVIDER=groq)"
        )
    if name == "codex":
        return name, os.environ.get("LLM_MODEL") or CODEX_MODEL
    if name in OPENAI_COMPATIBLE:
        provider = OPENAI_COMPATIBLE[name]
        if not os.environ.get(provider.key_env):
            raise ValueError(f"{provider.name}: {provider.key_env}가 없음")
        return name, os.environ.get("LLM_MODEL") or provider.model
    return name, os.environ.get("LLM_MODEL") or (
        "claude-sonnet-5-5" if os.environ.get("ANTHROPIC_API_KEY") else "CLI default"
    )


def daily_quota(message: str) -> bool:
    return bool(
        re.search(r"daily|per day|\b(?:RPD|TPD)\b|하루|일일", message, re.IGNORECASE)
    )


def md(text) -> str:
    return re.sub(r"([\\`*_{}\[\]<>#+|])", r"\\\1", re.sub(r"\s+", " ", str(text)))


def save_sheet(output: Path, record: dict) -> None:
    lines = [
        "# 댓글 비교",
        "",
        "영상 내용에 맞고 광고 말투가 덜한 쪽을 고른다. 검증 결과와 버전 정보는 key.json에 따로 저장한다.",
        "각 초안은 단발 생성(single-shot)이며, 검사 결과를 붙여 다시 쓰는 재작성 루프는 사용하지 않았다. 영상 자료는 실제 자막 또는 장면 설명과 영상 설명을 포함한다.",
        "각 버전에는 그 버전에서 앞서 만든 초안을 참고 이력으로 넘겼다. 두 버전의 이력은 섞지 않았다.",
        "각 버전은 같은 횟수만 호출했다. 네 후보 방식은 코드로 선택하며, 통과 후보가 없어도 재작성하지 않았다. 구체적인 선택 기준은 버전 키에 기록했다.",
        "",
    ]
    if record.get("provider"):
        lines += [
            f"두 버전 모두 {md(record['provider'])} · {md(record['model'])}로 고정했다. 공급자 자동 대체는 사용하지 않았다.",
            "",
        ]
    recovered = sum(
        len(d.get("error_history", []))
        for row in record["rows"]
        for d in row["drafts"].values()
    )
    if recovered:
        lines += [
            f"응답을 받지 못한 오류 {recovered}건은 추가 요청했으며, 이력은 key.json에 보존했다.",
            "",
        ]
    for index, row in enumerate(record["rows"], 1):
        ref = row["reference"]
        lines += [
            f"## {index}. {md(row['title'])}",
            "",
            f"영상: `{row['videoId']}`",
            "",
        ]
        for label in ("A", "B"):
            result = row["drafts"].get(row["labels"][label])
            if result is None:
                lines += [f"### {label}", "", "(미생성)", ""]
            elif result.get("error"):
                lines += [f"### {label}", "", "(생성 실패)", ""]
            else:
                lines += [
                    f"### {label} · {result['chars']}자",
                    "",
                    md(result["comment"]) or "(초안 거절)",
                    "",
                ]
        lines += [
            f"참고: 실제 최다 좋아요 댓글 ({ref['likes']}개, 최대 200자): {md(ref['text'])}",
            "",
            "선택: A / B / 비슷함",
            "",
        ]
    output.mkdir(parents=True, exist_ok=True)
    (output / "sheet.md").write_text("\n".join(lines), encoding="utf-8")
    temporary = output / "key.json.tmp"
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(output / "key.json")


def compare(
    contexts,
    rules,
    output: Path,
    *,
    old_builder,
    llm=complete,
    seed=None,
    backend="",
    delay=0,
    sleep=time.sleep,
    baseline_revision=BASE_REVISION,
    provider="",
    model="",
    transport="",
    effort="",
    cli_path="",
    empty_retries=1,
) -> dict:
    if (output / "key.json").exists() or (output / "sheet.md").exists():
        raise ValueError("비교 결과가 이미 있음. 다른 --output 폴더를 지정하세요")
    seed = random.SystemRandom().getrandbits(64) if seed is None else seed
    rng = random.Random(seed)
    record = {
        "baseline_revision": baseline_revision,
        "history_mode": "per-arm newest-first, no validation feedback",
        "backend": backend,
        "provider": provider,
        "model": model,
        "transport": transport,
        "effort": effort,
        "cli_path": cli_path,
        "new_candidate_count": 4,
        "old_candidate_count": 4 if baseline_revision == "f1c6e45" else 1,
        "selection": {
            "old": "diversity" if baseline_revision == "f1c6e45" else "single",
            "new": "register_then_diversity",
        },
        "empty_retry_limit": empty_retries,
        "prompt_variant": "short" if provider == "groq" else "full",
        "seed": seed,
        "delay_seconds": delay,
        "stop_reason": "",
        "rows": [],
    }
    for ctx in contexts:
        versions = ["old", "new"]
        rng.shuffle(versions)
        refs = voice_comments(ctx.get("topComments", []), brand=rules.brand)
        record["rows"].append(
            {
                "videoId": ctx["videoId"],
                "title": ctx["title"],
                "reference": refs[0]
                if refs
                else {"text": "(필터 후 댓글 없음)", "likes": 0},
                "labels": dict(zip(("A", "B"), versions)),
                "drafts": {},
            }
        )
    save_sheet(output, record)
    generated = 0
    histories = {"old": [], "new": []}
    for ctx, row in zip(contexts, record["rows"]):
        versions = ["old", "new"]
        rng.shuffle(versions)  # generation order is independent of blind display order
        for version in versions:
            errors = []
            for attempt in range(1, empty_retries + 2):
                if generated and delay:
                    sleep(delay)
                generated += 1
                print(
                    f"generate {ctx['videoId']} {version} attempt={attempt} provider={provider} model={model} effort={effort} transport={transport}",
                    flush=True,
                )
                metadata = {
                    "provider": provider,
                    "model": model,
                    "transport": transport,
                    "effort": effort,
                    "cli_path": cli_path,
                    "transcript_chars_sent": min(
                        SHORT_TRANSCRIPT_LIMIT
                        if provider == "groq"
                        else TRANSCRIPT_LIMIT,
                        len(ctx.get("transcript", "")),
                    ),
                    "prompt_variant": record["prompt_variant"],
                    "attempts": attempt,
                    "previous_count": len(histories[version]),
                }
                prompt_ctx = dict(ctx)
                if version == "old" and baseline_revision == "b53e4f7":
                    prompt_ctx["topComments"] = [
                        (str(c.get("text", "")) if isinstance(c, dict) else str(c))[
                            :200
                        ]
                        for c in ctx.get("topComments", [])
                    ][:20]
                builder = old_builder if version == "old" else build_prompt
                retry_empty = False
                try:
                    prompt = builder(
                        prompt_ctx,
                        brand=rules.brand,
                        min=rules.min,
                        max=rules.max,
                        previous=histories[version],
                    )
                    if provider == "groq":
                        prompt = getattr(prompt, "short", prompt)
                    raw = llm(prompt)
                    if not str(raw).strip():
                        raise RuntimeError("LLM이 빈 답을 돌려줌")
                    candidate_mode = version == "new" or baseline_revision == "f1c6e45"
                    if candidate_mode:
                        parsed = select_candidates(
                            parse_candidates(raw),
                            ctx,
                            brand=rules.brand,
                            min=rules.min,
                            max=rules.max,
                            previous=histories[version],
                            prefer_register=version == "new",
                        )
                        validation = parsed["validation"]
                    else:
                        parsed = parse_json(raw)
                        validation = validate_comment(
                            parsed["comment"],
                            source=source_text(ctx),
                            detail=parsed["detail"],
                            brand=rules.brand,
                            min=rules.min,
                            max=rules.max,
                            previous=histories[version],
                        )
                    if not parsed["relevant"]:
                        validation["ok"] = False
                        validation["errors"].append(
                            "연애와 관련 없는 영상으로 초안 거절"
                        )
                    row["drafts"][version] = {
                        **parsed,
                        **metadata,
                        "validation": validation,
                        "chars": validation["chars"],
                        "candidate_count": len(parsed.get("candidates", []))
                        if candidate_mode
                        else 1,
                        "error_history": list(errors),
                    }
                    if parsed["comment"] and parsed["relevant"]:
                        histories[version].insert(0, parsed["comment"])
                    print(
                        f"result {version}: {validation['chars']} chars, ok={validation['ok']}",
                        flush=True,
                    )
                except (
                    RuntimeError,
                    ValueError,
                    TypeError,
                    KeyError,
                    OSError,
                    httpx.HTTPError,
                ) as error:
                    message = safe_error(error)
                    row["drafts"][version] = {
                        **metadata,
                        "error": message,
                        "error_history": list(errors),
                        "chars": 0,
                        "validation": {"ok": False, "errors": [message]},
                    }
                    print(message, flush=True)
                    if daily_quota(message):
                        record["stop_reason"] = message
                    retry_empty = (
                        attempt <= empty_retries
                        and not record["stop_reason"]
                        and bool(re.search(r"빈\s*답|empty", message, re.IGNORECASE))
                    )
                    errors.append(message)
                save_sheet(output, record)
                if record["stop_reason"]:
                    return record
                if not retry_empty:
                    break
    return record


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument(
        "--contexts", type=Path, help="cached get_video_context JSON list"
    )
    parser.add_argument("--comments", type=Path, default=RESEARCH / "comments.jsonl")
    parser.add_argument("--output", type=Path, default=RESEARCH / "blind4")
    parser.add_argument("--require-codex-cli", action="store_true")
    parser.add_argument("--exclude-gold", action="store_true")
    parser.add_argument("--empty-retries", type=int, choices=(0, 1), default=0)
    parser.add_argument("--baseline", choices=tuple(BASELINES), default=BASE_REVISION)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--delay",
        type=float,
        default=0,
        help="seconds between generations (65 for Groq TPM limits)",
    )
    args = parser.parse_args(argv)
    if args.count < 1 or args.delay < 0:
        parser.error("--count must be positive and --delay nonnegative")
    if (args.output / "key.json").exists() or (args.output / "sheet.md").exists():
        print("비교 결과가 이미 있음. 다른 --output 폴더를 지정하세요", flush=True)
        return 1
    load_env()
    config = load_config()
    try:
        provider, model = configured_model()
        transport = (
            "cli"
            if provider == "codex"
            or (provider == "claude" and not os.environ.get("ANTHROPIC_API_KEY"))
            else "api"
        )
        effort = reasoning_effort() if provider == "codex" else ""
        cli_path = (
            shutil.which(os.environ.get("CODEX_CLI", "codex"))
            if provider == "codex"
            else ""
        )
        if args.require_codex_cli and (
            provider != "codex" or transport != "cli" or not cli_path
        ):
            raise ValueError(
                "이 비교는 Codex CLI 경로가 있는 LLM_PROVIDER=codex 설정이 필요함"
            )
        contexts = select_contexts(config, args.count, args.contexts)
        if args.exclude_gold and any(ctx["videoId"] in GOLD_IDS for ctx in contexts):
            raise ValueError("홀드아웃 비교에는 승인 예시 영상 5개를 넣을 수 없음")
        attach_likes(contexts, args.comments)
        result = compare(
            contexts,
            config.comment,
            args.output,
            old_builder=baseline_builder(args.baseline),
            seed=args.seed,
            backend=backend_name(),
            delay=args.delay,
            baseline_revision=args.baseline,
            provider=provider,
            model=model,
            transport=transport,
            effort=effort,
            cli_path=cli_path or "",
            empty_retries=args.empty_retries,
        )
    except (
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        httpx.HTTPError,
    ) as error:
        print(safe_error(error), flush=True)
        return 1
    print(f"sheet: {args.output / 'sheet.md'}", flush=True)
    print(f"key: {args.output / 'key.json'}", flush=True)
    failed = any(
        draft.get("error") for row in result["rows"] for draft in row["drafts"].values()
    )
    return 2 if result["stop_reason"] else 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
