from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download
from huggingface_hub.utils import enable_progress_bars
from tqdm.auto import tqdm

REPO_A = "huihui-ai/Huihui-InternVL3-14B-abliterated"
REPO_B = "Koitenshin/Huihui-InternVL3-14B-abliterated-GGUF"

DEST_A = Path(r"D:\AzusaFish\Codes\Development\Project-Avis\Tuning\LLaMa_Factory\InternVL3_0-14B-abliterated")
DEST_B = Path(r"D:\AzusaFish\Codes\Development\Project-Avis\Model\Base\InternVL14B")
CONFIG_YAML = Path(r"D:\AzusaFish\Codes\Development\Project-Avis\config.yaml")

TARGET_B_FILES = [
    "huihui-internvl3-14b-abliterated-q4_k_m.gguf",
    "mmproj-Huihui-InternVL3-14B-abliterated-F32.gguf",
]


def _force_hf_transfer(endpoint: str, token: str | None) -> None:
    os.environ["HF_ENDPOINT"] = endpoint.rstrip("/")
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    if token:
        os.environ["HF_TOKEN"] = token

    if importlib.util.find_spec("hf_transfer") is None:
        raise RuntimeError(
            "hf_transfer is not installed. Please run: pip install hf_transfer"
        )


def _cleanup_old_gguf(dest: Path, keep_names: set[str], dry_run: bool) -> list[str]:
    removed: list[str] = []
    for file in dest.glob("*.gguf"):
        if file.name in keep_names:
            continue
        removed.append(file.name)
        if not dry_run:
            file.unlink(missing_ok=True)
    return removed


def _switch_config_to_new_gguf(dry_run: bool) -> None:
    if not CONFIG_YAML.exists():
        print(f"[WARN] config not found: {CONFIG_YAML}")
        return

    mapping = {
        "GGUF_MODEL": TARGET_B_FILES[0],
        "GGUF_INTERNVL_MODEL": TARGET_B_FILES[0],
        "GGUF_MMPROJ_PATH": str(DEST_B / TARGET_B_FILES[1]),
    }

    original = CONFIG_YAML.read_text(encoding="utf-8")
    lines = original.splitlines()
    out_lines: list[str] = []
    touched = set()
    for line in lines:
        replaced = False
        for key, value in mapping.items():
            prefix = f"{key}:"
            if line.startswith(prefix):
                out_lines.append(f"{key}: {value}")
                touched.add(key)
                replaced = True
                break
        if not replaced:
            out_lines.append(line)

    for key, value in mapping.items():
        if key not in touched:
            out_lines.append(f"{key}: {value}")

    new_text = "\n".join(out_lines) + "\n"
    if dry_run:
        print("[DRY] Would update config keys:", ", ".join(mapping.keys()))
        return
    CONFIG_YAML.write_text(new_text, encoding="utf-8")
    print(f"[B] Updated config: {CONFIG_YAML}")


def _download_target_a(token: str | None, dry_run: bool) -> None:
    DEST_A.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"[DRY] A: would snapshot download {REPO_A} -> {DEST_A}")
        return

    print(f"[A] Downloading all files from {REPO_A}")
    snapshot_download(
        repo_id=REPO_A,
        local_dir=str(DEST_A),
        token=token,
    )


def _download_target_b(token: str | None, replace_existing: bool, dry_run: bool) -> None:
    DEST_B.mkdir(parents=True, exist_ok=True)
    keep = set(TARGET_B_FILES)

    if replace_existing and dry_run:
        removed = _cleanup_old_gguf(DEST_B, keep, dry_run=True)
        if removed:
            print(f"[DRY] B: would remove old GGUF files: {removed}")

    if dry_run:
        print(f"[DRY] B: would download files {TARGET_B_FILES} from {REPO_B} -> {DEST_B}")
        _switch_config_to_new_gguf(dry_run=True)
        return

    print(f"[B] Downloading selected GGUF files from {REPO_B}")
    for filename in tqdm(TARGET_B_FILES, desc="GGUF files", unit="file"):
        hf_hub_download(
            repo_id=REPO_B,
            filename=filename,
            local_dir=str(DEST_B),
            token=token,
        )

    _switch_config_to_new_gguf(dry_run=False)

    if replace_existing:
        removed = _cleanup_old_gguf(DEST_B, keep, dry_run=False)
        if removed:
            print(f"[B] Removed old GGUF files after successful download: {removed}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download InternVL assets via huggingface_hub + hf_transfer from mirror endpoint."
        )
    )
    parser.add_argument(
        "--endpoint",
        default="https://hf-mirror.com",
        help="HF mirror endpoint, default: https://hf-mirror.com",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HF_TOKEN", ""),
        help="HF token (optional for public repos).",
    )
    parser.add_argument("--skip-a", action="store_true", help="Skip target A full repo download.")
    parser.add_argument("--skip-b", action="store_true", help="Skip target B selected GGUF download.")
    parser.add_argument(
        "--no-replace-existing",
        action="store_true",
        help="Do not remove legacy GGUF files in target B before download.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without downloading.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token.strip() or None

    try:
        _force_hf_transfer(endpoint=args.endpoint, token=token)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 2

    enable_progress_bars()

    steps = []
    if not args.skip_a:
        steps.append("A")
    if not args.skip_b:
        steps.append("B")

    if not steps:
        print("Nothing to do. Use without --skip-* to download targets.")
        return 0

    for step in tqdm(steps, desc="Download plan", unit="task"):
        if step == "A":
            _download_target_a(token=token, dry_run=args.dry_run)
        elif step == "B":
            _download_target_b(
                token=token,
                replace_existing=not args.no_replace_existing,
                dry_run=args.dry_run,
            )

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
