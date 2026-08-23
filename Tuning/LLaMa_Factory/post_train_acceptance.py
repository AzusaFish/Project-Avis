from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request


GENERIC_PATTERNS = [
    re.compile(r"\bhow\s+(can|may|might)\s+i\s+(assist|help)\s+you(\s+(today|now))?\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+can\s+i\s+(assist|help)\s+you\s+with(\s+today)?\b", re.IGNORECASE),
    re.compile(r"\bhow\b.{0,24}\bi\b.{0,24}\b(assist|help)\s+you\b", re.IGNORECASE),
    re.compile(r"\bi(?:'m|\s+am)\s+here\s+to\s+(assist|help)\b", re.IGNORECASE),
    re.compile(r"\bas\s+an\s+ai\b", re.IGNORECASE),
    re.compile(r"\bvirtual\s+assistant\b", re.IGNORECASE),
]

STOPWORDS = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "for",
    "and",
    "or",
    "in",
    "on",
    "at",
    "with",
    "as",
    "that",
    "this",
    "it",
    "be",
    "by",
    "from",
    "you",
    "your",
    "i",
    "we",
    "he",
    "she",
    "they",
    "them",
    "our",
    "us",
    "me",
    "my",
    "do",
    "does",
    "did",
    "can",
    "could",
    "may",
    "might",
    "will",
    "would",
    "should",
    "have",
    "has",
    "had",
}


@dataclass
class DatasetLeakStats:
    total_rows: int
    chosen_generic_hits: int
    rejected_generic_hits: int
    chosen_generic_rate: float
    rejected_generic_rate: float
    pass_threshold: float
    passed: bool


@dataclass
class StaticContextStats:
    image_attached_for_tool_result: bool
    screenshot_path_memory_written: bool
    followup_image_reinjection_detected: bool
    screenshot_reference_possible_in_history: bool
    risk_summary: str


@dataclass
class ScreenshotCaseResult:
    name: str
    first_reply: str
    second_reply: str
    first_generic: bool
    second_generic: bool
    first_token_count: int
    second_token_count: int
    expected_keyword_hit_rate: float | None
    correctness_score: float
    consistency_jaccard: float
    first_request_image_count: int
    second_request_image_count: int
    second_request_screenshot_ref_count: int
    context_retention_passed: bool
    case_passed: bool


@dataclass
class AcceptanceReport:
    generated_at: str
    dpo_dataset_path: str
    core_url: str
    runtime_checks_executed: bool
    dataset_leak: DatasetLeakStats
    static_context: StaticContextStats
    screenshot_cases: list[ScreenshotCaseResult]
    overall_passed: bool
    notes: list[str]


def norm_text(text: str) -> str:
    return " ".join((text or "").strip().split()).lower()


def has_generic_style(text: str) -> bool:
    head = norm_text(text)[:400]
    if not head:
        return False
    return any(p.search(head) for p in GENERIC_PATTERNS)


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[A-Za-z0-9_\-]{2,}", norm_text(text))
    return {w for w in words if w not in STOPWORDS}


def jaccard_similarity(a: str, b: str) -> float:
    sa = tokenize(a)
    sb = tokenize(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / max(1, union)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_dataset_leak(dpo_dataset_path: Path, max_rate: float) -> DatasetLeakStats:
    rows = read_json(dpo_dataset_path)
    if not isinstance(rows, list):
        raise ValueError(f"DPO dataset must be a list: {dpo_dataset_path}")

    total = len(rows)
    chosen_hits = 0
    rejected_hits = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        chosen = str(row.get("chosen", ""))
        rejected = str(row.get("rejected", ""))
        if has_generic_style(chosen):
            chosen_hits += 1
        if has_generic_style(rejected):
            rejected_hits += 1

    chosen_rate = chosen_hits / max(1, total)
    rejected_rate = rejected_hits / max(1, total)
    passed = chosen_rate <= max_rate

    return DatasetLeakStats(
        total_rows=total,
        chosen_generic_hits=chosen_hits,
        rejected_generic_hits=rejected_hits,
        chosen_generic_rate=chosen_rate,
        rejected_generic_rate=rejected_rate,
        pass_threshold=max_rate,
        passed=passed,
    )


def evaluate_static_context(project_root: Path) -> StaticContextStats:
    loop_path = project_root / "Core" / "app" / "agent" / "loop.py"
    ctx_path = project_root / "Core" / "app" / "agent" / "context_manager.py"

    loop_text = loop_path.read_text(encoding="utf-8", errors="replace")
    ctx_text = ctx_path.read_text(encoding="utf-8", errors="replace")

    image_attached = "if vision_image_data_url and messages" in loop_text and "\"image_url\"" in loop_text
    screenshot_mem = "[TOOL_RESULT] screenshot_path=" in loop_text

    # If no dedicated persistence var exists, image is likely single-turn only and relies on text memory afterwards.
    followup_image_reinject = "vision_image_data_url" in loop_text and "self._last_screenshot" in loop_text

    screenshot_ref_possible = "role not in {\"user\", \"assistant\", \"system\", \"tool\"}" in ctx_text

    if image_attached and screenshot_mem and not followup_image_reinject:
        risk_summary = (
            "Screenshot image is injected only on tool-result turn; follow-up turns likely rely on text memory"
            " (screenshot_path/tool summary) rather than image reattachment."
        )
    else:
        risk_summary = "No obvious single-turn image injection risk detected by static scan."

    return StaticContextStats(
        image_attached_for_tool_result=image_attached,
        screenshot_path_memory_written=screenshot_mem,
        followup_image_reinjection_detected=followup_image_reinject,
        screenshot_reference_possible_in_history=screenshot_ref_possible,
        risk_summary=risk_summary,
    )


def http_json(method: str, url: str, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    body = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if isinstance(data, dict) and "code" in data and "data" in data:
        return data
    return {"code": 0, "data": data, "message": "ok"}


def core_is_ready(core_url: str) -> bool:
    try:
        result = http_json("GET", f"{core_url.rstrip('/')}/api/v1/health", timeout=5.0)
        return int(result.get("code", 1)) == 0
    except Exception:
        return False


def latest_dialogue_item(core_url: str, role: str) -> dict[str, Any] | None:
    q = parse.urlencode(
        {
            "role": role,
            "limit": 1,
            "offset": 0,
            "sort_by": "time",
        }
    )
    result = http_json("GET", f"{core_url.rstrip('/')}/api/v1/memory/dialogues?{q}", timeout=10.0)
    data = result.get("data") or {}
    items = data.get("items") or []
    if not items:
        return None
    return items[0]


def find_latest_screenshot_tool_item(core_url: str) -> dict[str, Any] | None:
    q = parse.urlencode(
        {
            "role": "tool",
            "q": "screenshot_path=",
            "limit": 5,
            "offset": 0,
            "sort_by": "time",
        }
    )
    result = http_json("GET", f"{core_url.rstrip('/')}/api/v1/memory/dialogues?{q}", timeout=10.0)
    data = result.get("data") or {}
    items = data.get("items") or []
    return items[0] if items else None


def inject_text(core_url: str, text: str) -> None:
    result = http_json(
        "POST",
        f"{core_url.rstrip('/')}/api/v1/control/inject-text",
        payload={"text": text},
        timeout=10.0,
    )
    if int(result.get("code", 1)) != 0:
        raise RuntimeError(f"inject-text failed: {result}")


def wait_new_assistant_reply(core_url: str, after_id: int, timeout_sec: float) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        item = latest_dialogue_item(core_url, role="assistant")
        if item and int(item.get("id", 0)) > after_id:
            return item
        time.sleep(0.6)
    raise TimeoutError("Timed out waiting for assistant reply")


def get_llm_io_payload(core_url: str) -> dict[str, Any]:
    result = http_json("GET", f"{core_url.rstrip('/')}/api/v1/debug/llm-io", timeout=10.0)
    if int(result.get("code", 1)) != 0:
        return {}
    data = result.get("data") or {}
    payload = data.get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def analyze_last_request(payload: dict[str, Any]) -> tuple[int, int]:
    req = payload.get("last_request") or {}
    messages = req.get("messages") or []
    image_count = 0
    screenshot_ref_count = 0
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            screenshot_ref_count += content.count("screenshot_path=")
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image_url":
                    image_count += 1
                if part.get("type") == "text":
                    t = str(part.get("text", ""))
                    screenshot_ref_count += t.count("screenshot_path=")
    return image_count, screenshot_ref_count


def keyword_hit_rate(text: str, expected_keywords: list[str]) -> float | None:
    if not expected_keywords:
        return None
    low = norm_text(text)
    hits = 0
    for kw in expected_keywords:
        kw_norm = norm_text(str(kw))
        if kw_norm and kw_norm in low:
            hits += 1
    return hits / max(1, len(expected_keywords))


def evaluate_screenshot_case(
    core_url: str,
    case: dict[str, Any],
    wait_timeout_sec: float,
) -> ScreenshotCaseResult:
    name = str(case.get("name", "unnamed_case"))
    prompt = str(case.get("prompt", "")).strip()
    if not prompt:
        raise ValueError(f"case '{name}' missing prompt")

    followup_prompt = str(
        case.get(
            "followup_prompt",
            "Using the same screenshot as just now, summarize the key visible facts in one concise sentence. Keep facts consistent.",
        )
    ).strip()
    expected_keywords = [str(x).strip() for x in (case.get("expected_keywords") or []) if str(x).strip()]

    before = latest_dialogue_item(core_url, role="assistant")
    before_id = int(before.get("id", 0)) if before else 0

    tag = f"ACC_CASE_{int(time.time())}_{name}"
    inject_text(core_url, f"{prompt}\n\n[acceptance_tag:{tag}]")
    first_item = wait_new_assistant_reply(core_url, after_id=before_id, timeout_sec=wait_timeout_sec)
    first_reply = str(first_item.get("text", "")).strip()
    payload1 = get_llm_io_payload(core_url)
    first_img_count, _ = analyze_last_request(payload1)

    first_generic = has_generic_style(first_reply)
    first_tokens = len(tokenize(first_reply))

    kw_rate = keyword_hit_rate(first_reply, expected_keywords)
    kw_component = 0.5 if kw_rate is None else kw_rate
    informative_component = 1.0 if first_tokens >= 18 else first_tokens / 18.0
    nongeneric_component = 0.0 if first_generic else 1.0
    correctness_score = 0.35 * nongeneric_component + 0.25 * informative_component + 0.40 * kw_component

    after_first_id = int(first_item.get("id", 0))
    inject_text(core_url, f"{followup_prompt}\n\n[acceptance_tag:{tag}]" )
    second_item = wait_new_assistant_reply(core_url, after_id=after_first_id, timeout_sec=wait_timeout_sec)
    second_reply = str(second_item.get("text", "")).strip()
    payload2 = get_llm_io_payload(core_url)
    second_img_count, second_ref_count = analyze_last_request(payload2)

    second_generic = has_generic_style(second_reply)
    second_tokens = len(tokenize(second_reply))
    consistency_j = jaccard_similarity(first_reply, second_reply)

    context_retained = second_img_count > 0 or second_ref_count > 0
    case_pass = (
        correctness_score >= 0.60
        and consistency_j >= 0.18
        and (not first_generic)
        and (not second_generic)
        and context_retained
    )

    return ScreenshotCaseResult(
        name=name,
        first_reply=first_reply,
        second_reply=second_reply,
        first_generic=first_generic,
        second_generic=second_generic,
        first_token_count=first_tokens,
        second_token_count=second_tokens,
        expected_keyword_hit_rate=kw_rate,
        correctness_score=correctness_score,
        consistency_jaccard=consistency_j,
        first_request_image_count=first_img_count,
        second_request_image_count=second_img_count,
        second_request_screenshot_ref_count=second_ref_count,
        context_retention_passed=context_retained,
        case_passed=case_pass,
    )


def load_screenshot_cases(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return [
            {
                "name": "desktop_live_case",
                "prompt": "Please call desktop_screenshot tool now and describe exactly what is visible on my current desktop. Mention app names, file names, or code keywords if readable.",
                "followup_prompt": "Using the same screenshot as just now, summarize the key visible facts in one concise sentence. Keep facts consistent.",
                "expected_keywords": [],
            }
        ]

    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError(f"screenshot cases file must be a list: {path}")
    return [x for x in data if isinstance(x, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-training acceptance checks for Project-Avis tuning pipeline")
    parser.add_argument("--project-root", default="../..")
    parser.add_argument("--dpo-dataset", default="datasets/neuro_uncensored_dpo_en.json")
    parser.add_argument("--core-url", default="http://127.0.0.1:8080")
    parser.add_argument("--screenshot-cases", default="")
    parser.add_argument("--output-dir", default="acceptance_reports")
    parser.add_argument("--max-generic-rate", type=float, default=0.005)
    parser.add_argument("--reply-timeout-sec", type=float, default=60.0)
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    project_root = (base_dir / args.project_root).resolve()
    dpo_dataset_path = (base_dir / args.dpo_dataset).resolve()
    cases_path = (base_dir / args.screenshot_cases).resolve() if args.screenshot_cases else None
    output_dir = (base_dir / args.output_dir).resolve()

    notes: list[str] = []

    if not dpo_dataset_path.exists():
        raise FileNotFoundError(f"DPO dataset not found: {dpo_dataset_path}")

    dataset_stats = evaluate_dataset_leak(dpo_dataset_path=dpo_dataset_path, max_rate=float(args.max_generic_rate))
    static_stats = evaluate_static_context(project_root=project_root)

    runtime_ready = core_is_ready(args.core_url)
    runtime_cases: list[ScreenshotCaseResult] = []

    if runtime_ready:
        cases = load_screenshot_cases(cases_path)
        for case in cases:
            try:
                result = evaluate_screenshot_case(
                    core_url=args.core_url,
                    case=case,
                    wait_timeout_sec=float(args.reply_timeout_sec),
                )
                runtime_cases.append(result)
            except Exception as exc:
                notes.append(f"runtime case failed ({case.get('name', 'unnamed')}): {exc}")
    else:
        notes.append("Core runtime not reachable at /api/v1/health; screenshot runtime checks skipped")

    if args.require_runtime and not runtime_ready:
        notes.append("--require-runtime is set, but Core is unavailable")

    runtime_pass = True
    if runtime_cases:
        runtime_pass = all(x.case_passed for x in runtime_cases)

    overall_pass = dataset_stats.passed and runtime_pass
    if args.require_runtime:
        overall_pass = overall_pass and runtime_ready and bool(runtime_cases)

    report = AcceptanceReport(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        dpo_dataset_path=str(dpo_dataset_path),
        core_url=args.core_url,
        runtime_checks_executed=runtime_ready and bool(runtime_cases),
        dataset_leak=dataset_stats,
        static_context=static_stats,
        screenshot_cases=runtime_cases,
        overall_passed=overall_pass,
        notes=notes,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"acceptance_{ts}.json"
    write_json(out_path, asdict(report))

    print("[ACCEPT] report:", out_path)
    print("[ACCEPT] dataset chosen generic rate:", f"{dataset_stats.chosen_generic_rate:.4%}")
    print("[ACCEPT] dataset pass threshold:", f"{dataset_stats.pass_threshold:.4%}")
    print("[ACCEPT] static context risk:", static_stats.risk_summary)
    if runtime_cases:
        passed_count = sum(1 for x in runtime_cases if x.case_passed)
        print(f"[ACCEPT] screenshot runtime cases: {passed_count}/{len(runtime_cases)} passed")
    else:
        print("[ACCEPT] screenshot runtime cases: skipped")

    for msg in notes:
        print("[ACCEPT][NOTE]", msg)

    return 0 if overall_pass else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except error.URLError as exc:
        print(f"[ERROR] network/url error: {exc}")
        raise SystemExit(2)
    except Exception as exc:
        print(f"[ERROR] acceptance check failed: {exc}")
        raise SystemExit(2)
