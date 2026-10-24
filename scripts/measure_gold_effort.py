"""Compare low/medium constraint compliance, not subjective comment quality."""

import argparse
import hashlib
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.config import load_config, load_env
from agent.generate import build_prompt, parse_candidates, register_match
from agent.llm import complete, reasoning_effort
from agent.voice_examples import GOLD_IDS
from scripts.compare_voice import configured_model


def measure(contexts, rules, *, llm=complete, delay=5, sleep=time.sleep):
    if any(
        ctx["videoId"] in GOLD_IDS or not ctx.get("transcript", "").strip()
        for ctx in contexts
    ):
        raise ValueError("추론 수준 측정은 자막 있는 비예시 영상만 사용")
    rows = []
    original = os.environ.get("LLM_REASONING_EFFORT")
    try:
        for ctx in contexts:
            prompt = build_prompt(ctx, brand=rules.brand, min=rules.min, max=rules.max)
            for effort in ("low", "medium"):
                if rows and delay:
                    sleep(delay)
                os.environ["LLM_REASONING_EFFORT"] = effort
                row = {
                    "videoId": ctx["videoId"],
                    "effort": reasoning_effort(),
                    "prompt_sha256": hashlib.sha256(str(prompt).encode()).hexdigest(),
                    "candidate_count": 4,
                    "failed_candidates": 0,
                    "candidates": [],
                }
                try:
                    candidates = parse_candidates(llm(prompt))
                    if len(candidates) != 4 or not all(
                        c["relevant"] for c in candidates
                    ):
                        raise ValueError("expected four relevant candidates")
                    for candidate in candidates:
                        comment = candidate["comment"]
                        questions = unicodedata.normalize("NFKC", comment).count("?")
                        brands = comment.count(rules.brand)
                        failed = questions > 1 or brands != 1
                        row["failed_candidates"] += int(failed)
                        row["candidates"].append(
                            {
                                "comment": comment,
                                "questions": questions,
                                "brand_count": brands,
                                "register": register_match(comment),
                            }
                        )
                except ValueError as error:
                    row.update(error_type=type(error).__name__, failed_candidates=4)
                rows.append(row)
                print(
                    f"effort {ctx['videoId']} {effort}: {row['failed_candidates']}/4 question/brand/response failures",
                    flush=True,
                )
    finally:
        if original is None:
            os.environ.pop("LLM_REASONING_EFFORT", None)
        else:
            os.environ["LLM_REASONING_EFFORT"] = original
    totals = {
        effort: sum(row["failed_candidates"] for row in rows if row["effort"] == effort)
        for effort in ("low", "medium")
    }
    chosen = "medium" if totals["medium"] < totals["low"] else "low"
    return {
        "rows": rows,
        "failed_candidates": totals,
        "chosen_effort": chosen,
        "decision": "Choose fewer missing/duplicate-brand, multi-question or absent-response candidates; low breaks ties. Small calibration sample, not a quality claim.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contexts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    load_env()
    provider, model = configured_model()
    if provider != "codex" or model != "gpt-6-luna":
        raise ValueError("측정은 codex/gpt-6-luna만 사용")
    contexts = json.loads(args.contexts.read_text())[:3]
    result = {
        "provider": provider,
        "model": model,
        **measure(contexts, load_config().comment),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"chosen effort: {result['chosen_effort']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
