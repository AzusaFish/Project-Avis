import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

import download_full_base
import psutil

ROOT = Path(__file__).resolve().parent
EXPORT_SCRIPT = ROOT / "export.py"
ONE_CLICK_LOG = ROOT / "exports" / "one_click_export.log"


def setup_logger() -> logging.Logger:
    ONE_CLICK_LOG.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("one_click_export")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(ONE_CLICK_LOG, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    return logger


def run_and_stream(cmd: list[str], env: dict[str, str], logger: logging.Logger) -> int:
    logger.info("Running command: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        logger.info("[export] %s", line)
    return proc.wait()


def run_export(logger: logging.Logger) -> None:
    cmd = [sys.executable, str(EXPORT_SCRIPT)]
    logger.info("Running export.py ...")
    env = os.environ.copy()
    rc = run_and_stream(cmd, env, logger)
    if rc == 0:
        return

    logger.warning(
        "export.py failed with exit code %s. Retrying once in CPU-only safe mode...",
        rc,
    )
    env["AVIS_EXPORT_CPU_ONLY"] = "1"
    rc2 = run_and_stream(cmd, env, logger)
    if rc2 != 0:
        raise RuntimeError(
            f"export.py failed with exit code {rc}, "
            f"CPU-only retry failed with exit code {rc2}"
        )


def top_memory_processes(limit: int = 8) -> list[tuple[str, int]]:
    rows = []
    for p in psutil.process_iter(attrs=["name", "memory_info"]):
        try:
            rss = int(p.info["memory_info"].rss)
            rows.append((p.info["name"] or "unknown", rss))
        except Exception:
            continue
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:limit]


def maybe_stop_ollama(logger: logging.Logger, stop_ollama: bool) -> None:
    ollama_pids = []
    for p in psutil.process_iter(attrs=["pid", "name"]):
        try:
            name = (p.info["name"] or "").lower()
            if "ollama" in name:
                ollama_pids.append(p.info["pid"])
        except Exception:
            continue

    if not ollama_pids:
        return

    if not stop_ollama:
        raise RuntimeError(
            "Detected running ollama process(es). This export is memory-heavy and may crash Windows when ollama is active. "
            "Close ollama first, or rerun with --stop-ollama."
        )

    for pid in ollama_pids:
        try:
            psutil.Process(pid).terminate()
            logger.warning("Terminated ollama pid=%s for memory safety.", pid)
        except Exception as e:
            logger.warning("Failed to terminate ollama pid=%s: %s", pid, e)


def preflight_memory_guard(logger: logging.Logger, stop_ollama: bool) -> None:
    maybe_stop_ollama(logger, stop_ollama)

    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    avail_ram_gb = vm.available / (1024 ** 3)
    free_swap_gb = sm.free / (1024 ** 3)
    total_swap_gb = sm.total / (1024 ** 3)

    logger.info(
        "Memory preflight: RAM available=%.2f GB, pagefile free=%.2f GB, pagefile total=%.2f GB",
        avail_ram_gb,
        free_swap_gb,
        total_swap_gb,
    )

    if total_swap_gb < 48:
        raise RuntimeError(
            "Pagefile is too small for this export pipeline. Please set Windows virtual memory (pagefile) to at least 48GB (recommended 64GB), reboot, then retry."
        )

    if avail_ram_gb < 8 or free_swap_gb < 16:
        tops = top_memory_processes()
        detail = ", ".join(f"{name}:{rss/(1024**3):.1f}GB" for name, rss in tops)
        raise RuntimeError(
            "Insufficient memory headroom for safe export. "
            f"Top memory processes: {detail}. "
            "Close heavy apps (especially ollama / browsers / extra VSCode windows) and retry."
        )


def main() -> None:
    logger = setup_logger()
    logger.info("one_click_export started")
    parser = argparse.ArgumentParser(
        description="One-click: download full base shards, verify completeness, then export Q4_K_M GGUF."
    )
    parser.add_argument("--token", default=None, help="Optional Hugging Face token")
    parser.add_argument(
        "--stop-ollama",
        action="store_true",
        help="Auto-terminate running ollama process before export for memory safety",
    )
    args = parser.parse_args()

    if args.token:
        os.environ["HF_TOKEN"] = args.token

    logger.info("Python: %s", sys.executable)
    logger.info("HF token set: %s", bool(os.environ.get("HF_TOKEN")))

    preflight_memory_guard(logger, stop_ollama=args.stop_ollama)

    snapshot_dir, shard_files = download_full_base.download_all()
    missing = download_full_base.get_missing_shards(snapshot_dir, shard_files)
    if missing:
        logger.error("Still missing %s shard(s).", len(missing))
        for s in missing:
            logger.error("- %s", s)
        raise SystemExit(1)

    logger.info("All 8 shards are complete. Starting export + Q4_K_M quantization...")
    run_export(logger)
    logger.info("Pipeline finished.")


if __name__ == "__main__":
    main()
