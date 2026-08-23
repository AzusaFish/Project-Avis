import json
import pathlib
import sys


def main() -> int:
    report_path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "datasets/prepare_report.json")
    if not report_path.exists():
        print(f"[CHECK] prepare report missing: {report_path}")
        return 1

    with report_path.open("r", encoding="utf-8") as f:
        report = json.load(f)

    stats = report.get("stats", {})
    target = int(stats.get("vision_target", 0) or 0)
    kept = int(report.get("vision_records", 0) or 0)
    enabled = bool(report.get("vision_in_sft_enabled"))

    print(
        f"[CHECK] vision_in_sft_enabled={enabled}, vision_records={kept}, vision_target={target}"
    )

    ok = enabled and kept >= target and target > 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
