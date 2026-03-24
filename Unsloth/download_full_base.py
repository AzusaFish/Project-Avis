import json
import os
import socket
import time
from pathlib import Path

from huggingface_hub import hf_hub_download
from huggingface_hub.errors import RemoteEntryNotFoundError
from tqdm.auto import tqdm

REPO_ID = "Qwen/Qwen2.5-14B-Instruct"
CACHE_DIR = "d:/AzusaFish/Codes/Development/Project-Avis/Unsloth/hf_cache"
CLASH_PROXY = "http://127.0.0.1:7897"

# Speed-up knobs. HF token is optional but strongly recommended for better limits.
# Note: hf_transfer can bypass/ignore some proxy setups. Keep it off by default for stability.
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "30")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "1800")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# If you are in CN and direct HF is slow, uncomment the next line:
#os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


REQUIRED_FILES = [
    "config.json",
    "generation_config.json",
    "model.safetensors.index.json",
]

OPTIONAL_FILES = [
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "merges.txt",
    "vocab.json",
]


def get_snapshot_dir() -> Path:
    repo_cache = Path(CACHE_DIR) / "models--Qwen--Qwen2.5-14B-Instruct"
    ref_main = repo_cache / "refs" / "main"
    if not ref_main.exists():
        raise FileNotFoundError(f"Missing refs/main: {ref_main}")
    commit = ref_main.read_text(encoding="utf-8").strip()
    snapshot_dir = repo_cache / "snapshots" / commit
    if not snapshot_dir.exists():
        raise FileNotFoundError(f"Missing snapshot dir: {snapshot_dir}")
    return snapshot_dir


def get_shard_files(index_path: Path) -> list[str]:
    index = json.loads(index_path.read_text(encoding="utf-8"))
    weight_map = index.get("weight_map", {})
    shard_files = sorted(set(weight_map.values()))
    if not shard_files:
        raise RuntimeError("No shard files found in model.safetensors.index.json")
    return shard_files


def get_missing_shards(snapshot_dir: Path, shard_files: list[str]) -> list[str]:
    missing = []
    for shard in shard_files:
        if not (snapshot_dir / shard).exists():
            missing.append(shard)
    return missing


def clash_proxy_available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 7897), timeout=1.5):
            return True
    except OSError:
        return False


def ensure_proxy_env() -> None:
    has_proxy = any(os.environ.get(k) for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"])
    if has_proxy:
        print("Proxy env already set in current shell.", flush=True)
        return

    if clash_proxy_available():
        os.environ["HTTP_PROXY"] = CLASH_PROXY
        os.environ["HTTPS_PROXY"] = CLASH_PROXY
        os.environ["ALL_PROXY"] = CLASH_PROXY
        print(f"Auto proxy enabled: {CLASH_PROXY}", flush=True)
    else:
        print("No proxy env and Clash 7897 not reachable; will use direct connection.", flush=True)


def download_file(filename: str) -> str:
    print(f"START {filename}", flush=True)
    last_error = None
    for attempt in range(1, 8):
        try:
            return hf_hub_download(
                repo_id=REPO_ID,
                filename=filename,
                cache_dir=CACHE_DIR,
                local_files_only=False,
                force_download=False,
                etag_timeout=120,
            )
        except RemoteEntryNotFoundError:
            # 404 is deterministic; let caller decide whether to fail or skip.
            raise
        except Exception as e:
            last_error = e
            wait_s = min(60, 5 * attempt)
            print(f"Retry {attempt}/7 for {filename}: {e}", flush=True)
            print(f"Waiting {wait_s}s before retry...", flush=True)
            time.sleep(wait_s)
    raise RuntimeError(f"Failed downloading {filename} after retries: {last_error}")


def main() -> None:
    snapshot_dir, shard_files = download_all()
    missing = get_missing_shards(snapshot_dir, shard_files)
    if missing:
        print(f"Download incomplete. Missing shards: {len(missing)}")
        for s in missing:
            print(f"- {s}")
        raise SystemExit(1)
    print("All required files downloaded (or already cached).")


def download_all() -> tuple[Path, list[str]]:
    ensure_proxy_env()
    print(f"Repo: {REPO_ID}")
    print(f"Cache: {CACHE_DIR}")
    print(f"HF token set: {bool(os.environ.get('HF_TOKEN'))}")

    for f in REQUIRED_FILES:
        p = download_file(f)
        print(f"OK {f} -> {p}")

    for f in OPTIONAL_FILES:
        try:
            p = download_file(f)
            print(f"OK {f} -> {p}")
        except RemoteEntryNotFoundError:
            print(f"SKIP optional file not found: {f}")

    index_path = Path(download_file("model.safetensors.index.json"))
    shard_files = get_shard_files(index_path)
    snapshot_dir = get_snapshot_dir()

    print(f"Need shard files: {len(shard_files)}")
    bar = tqdm(total=len(shard_files), desc="Shard progress", unit="file")
    try:
        for i, shard in enumerate(shard_files, 1):
            bar.set_postfix_str(f"{i}/{len(shard_files)} {shard}")
            p = download_file(shard)
            print(f"[{i}/{len(shard_files)}] OK {shard} -> {p}")
            bar.update(1)
    finally:
        bar.close()

    return snapshot_dir, shard_files


if __name__ == "__main__":
    main()
