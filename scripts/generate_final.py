"""Generate a single review sheet through the dashboard's normal draft/retry path."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import load_config, load_env
from agent.generate import InsufficientVideoContent, UnrelatedVideo, draft_comment
from agent.llm import complete, reasoning_effort
from scripts.compare_voice import configured_model, md, safe_error


def save(record, output):
    lines = [
        "# 댓글 검토표",
        "",
        "새 세션에서 앞서 만든 초안을 이력으로 사용했다. 대시보드의 생성·검사·최대 3회 피드백 경로를 그대로 사용했으며 게시하지 않았다.",
        "",
    ]
    for row in record["rows"]:
        lines += [f"## {md(row['title'])}", "", f"영상: `{row['videoId']}`", ""]
        draft = row.get("draft")
        if draft:
            lines += [
                f"선택 댓글 ({draft['validation']['chars']}자): {md(draft['comment'])}",
                "",
                f"검사: {'통과' if draft['validation']['ok'] else '실패'} · 생성 {draft['attempts']}회",
                "",
            ]
            lines += [f"- {md(error)}" for error in draft["validation"]["errors"]]
            lines += [""]
        else:
            lines += [f"검사: 생성 실패 — {md(row['error'])}", ""]
    if record.get("stop_reason"):
        lines += [f"중단: {md(record['stop_reason'])}", ""]
    (output / "sheet.md").write_text("\n".join(lines))
    temporary = output / "key.json.tmp"
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    temporary.replace(output / "key.json")


def generate(
    contexts, rules, output, *, llm=complete, delay=5, sleep=time.sleep, effort="low"
):
    output.mkdir(
        parents=True, exist_ok=False
    )  # claim this result; never overwrite earlier runs
    record = {
        "provider": "codex",
        "model": "gpt-6-luna",
        "effort": effort,
        "transport": "cli",
        "history": "fresh session drafts, no pre-existing posted history",
        "rows": [],
        "stop_reason": "",
    }
    history, calls = [], 0
    save(record, output)
    for ctx in contexts:
        row = {"videoId": ctx["videoId"], "title": ctx["title"]}

        def paced(prompt, video_id=ctx["videoId"]):
            nonlocal calls
            if calls and delay:
                sleep(delay)
            calls += 1
            print(
                f"generate {video_id} request={calls} codex/gpt-6-luna/{effort}",
                flush=True,
            )
            return llm(prompt)

        try:
            draft = draft_comment(
                ctx,
                brand=rules.brand,
                min=rules.min,
                max=rules.max,
                previous=history,
                llm=paced,
            )
            row["draft"] = draft
            if draft["comment"]:
                history.insert(0, draft["comment"])
            print(
                f"result {ctx['videoId']}: attempts={draft['attempts']} chars={draft['validation']['chars']} ok={draft['validation']['ok']}",
                flush=True,
            )
        except (ValueError, UnrelatedVideo, InsufficientVideoContent) as error:
            row["error"] = safe_error(error)
        except RuntimeError as error:
            row["error"] = safe_error(error)
            record["stop_reason"] = row["error"]
        record["rows"].append(row)
        record["llm_calls"] = calls
        save(record, output)
        if record["stop_reason"]:
            break
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--order-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    load_env()
    if configured_model() != ("codex", "gpt-6-luna") or reasoning_effort() != "low":
        raise ValueError("최종 검토표는 codex/gpt-6-luna/low만 사용")
    config = load_config()
    cached = {ctx["videoId"]: ctx for ctx in json.loads(args.contexts.read_text())}
    ordered = [
        cached[row["videoId"]] for row in json.loads(args.order_key.read_text())["rows"]
    ]
    allowed = {channel.id for channel in config.channels}
    if (
        len(ordered) != 8
        or len({ctx["videoId"] for ctx in ordered}) != 8
        or any(
            ctx.get("channelId") not in allowed or not ctx.get("transcript", "").strip()
            for ctx in ordered
        )
    ):
        raise ValueError("같은 지정 채널 자막 영상 8개가 필요함")
    record = generate(ordered, config.comment, args.output, effort=reasoning_effort())
    print(f"sheet: {args.output / 'sheet.md'}", flush=True)
    return 1 if record["stop_reason"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
