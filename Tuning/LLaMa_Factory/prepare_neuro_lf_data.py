"""Prepare English SFT/DPO datasets and training YAMLs for LLaMA-Factory.

Pipeline goals:
1) Use qlora_cleaned_manual.jsonl (Neuro original quotes) as SFT core.
2) Build DPO preference pairs from uncensored-friendly datasets.
3) Optionally use local Ollama model to normalize SFT assistant text.
4) Generate ready-to-run YAML configs for 16 GB VRAM GPUs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import random
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PrepareStats:
    sft_total: int = 0
    sft_kept: int = 0
    sft_parse_error: int = 0
    sft_ollama_cleaned: int = 0
    dpo_total: int = 0
    dpo_kept: int = 0
    dpo_dedup_dropped: int = 0
    dpo_invalid_dropped: int = 0
    vision_target: int = 0
    vision_candidates: int = 0
    vision_kept: int = 0
    vision_existing: int = 0
    vision_downloaded_new: int = 0
    vision_download_failed: int = 0


@dataclass
class TrainProfile:
    sft_cutoff_len: int
    dpo_cutoff_len: int
    sft_grad_accum: int
    dpo_grad_accum: int
    sft_learning_rate: float
    dpo_learning_rate: float
    sft_epochs: float
    dpo_epochs: float
    dataloader_workers: int
    preprocessing_workers: int


def resolve_train_profile(model_name_or_path: str) -> TrainProfile:
    model_lower = model_name_or_path.lower()
    if "internvl" in model_lower and "14b" in model_lower:
        # 16 GB safe profile for InternVL3.5-14B + 4-bit QLoRA.
        return TrainProfile(
            sft_cutoff_len=384,
            dpo_cutoff_len=320,
            sft_grad_accum=32,
            dpo_grad_accum=48,
            sft_learning_rate=8.0e-5,
            # Keep DPO updates conservative to reduce catastrophic forgetting on vision abilities.
            dpo_learning_rate=2.0e-6,
            sft_epochs=5.0,
            dpo_epochs=1.0,
            # Python 3.14 + custom remote-code models can fail pickling in worker processes.
            dataloader_workers=0,
            preprocessing_workers=1,
        )

    return TrainProfile(
        sft_cutoff_len=1024,
        dpo_cutoff_len=1536,
        sft_grad_accum=16,
        dpo_grad_accum=16,
        sft_learning_rate=1.0e-4,
        dpo_learning_rate=5.0e-6,
        sft_epochs=6.0,
        dpo_epochs=2.0,
        dataloader_workers=2,
        preprocessing_workers=8,
    )


def ensure_internvl_tokenizer_config(base_dir: Path, model_name_or_path: str) -> None:
    model_lower = model_name_or_path.lower()
    if "internvl" not in model_lower:
        return

    model_path = Path(model_name_or_path)
    if not model_path.is_absolute():
        model_path = (base_dir / model_path).resolve()

    tokenizer_cfg_path = model_path / "tokenizer_config.json"
    if not tokenizer_cfg_path.exists():
        print(f"[WARN] tokenizer_config.json not found, skip InternVL tokenizer fix: {tokenizer_cfg_path}")
        return

    try:
        cfg = json.loads(tokenizer_cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] failed to read tokenizer_config.json, skip InternVL tokenizer fix: {exc}")
        return

    if not isinstance(cfg, dict):
        print("[WARN] tokenizer_config root is not an object, skip InternVL tokenizer fix")
        return

    required_tokens = {
        "start_image_token": "<img>",
        "end_image_token": "</img>",
        "context_image_token": "<IMG_CONTEXT>",
        "video_token": "<|video_pad|>",
    }

    extra = cfg.get("extra_special_tokens")
    if not isinstance(extra, dict):
        extra = {}

    changed = False
    for key, val in required_tokens.items():
        if extra.get(key) != val:
            extra[key] = val
            changed = True

    additional = cfg.get("additional_special_tokens")
    if not isinstance(additional, list):
        additional = []
        changed = True
    for val in required_tokens.values():
        if val not in additional:
            additional.append(val)
            changed = True

    cfg["extra_special_tokens"] = extra
    cfg["additional_special_tokens"] = additional

    if not changed:
        print("[INFO] InternVL tokenizer compatibility already satisfied.")
        return

    tokenizer_cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] Patched InternVL tokenizer compatibility fields: {tokenizer_cfg_path}")


def estimate_vram_gb(model_name_or_path: str, profile: TrainProfile) -> dict[str, float]:
    model_lower = model_name_or_path.lower()

    if "internvl" in model_lower and "14b" in model_lower:
        base_qlora = 9.2
        sft_peak = base_qlora + 1.8 + 2.2 * (profile.sft_cutoff_len / 512.0)
        dpo_peak = base_qlora + 2.4 + 3.0 * (profile.dpo_cutoff_len / 512.0)
    elif "7b" in model_lower:
        base_qlora = 5.2
        sft_peak = base_qlora + 1.4 + 1.6 * (profile.sft_cutoff_len / 1024.0)
        dpo_peak = base_qlora + 2.0 + 2.2 * (profile.dpo_cutoff_len / 1024.0)
    else:
        base_qlora = 7.0
        sft_peak = base_qlora + 1.6 + 1.8 * (profile.sft_cutoff_len / 1024.0)
        dpo_peak = base_qlora + 2.2 + 2.6 * (profile.dpo_cutoff_len / 1024.0)

    # Leave headroom for fragmentation, dataloader spikes, and runtime variance.
    recommended_vram = max(sft_peak, dpo_peak) + 1.2
    return {
        "estimated_sft_peak_gb": round(sft_peak, 2),
        "estimated_dpo_peak_gb": round(dpo_peak, 2),
        "recommended_gpu_vram_gb": round(recommended_vram, 2),
    }


def download_with_retries(
    url: str,
    out_path: Path,
    timeout_sec: int,
    max_retries: int,
) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url=url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = resp.read()
            if not data:
                raise RuntimeError("empty response")
            tmp_path.write_bytes(data)
            tmp_path.replace(out_path)
            return True
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            if attempt >= max_retries:
                return False

    return False


def normalize_sharegpt4v_row(row: dict[str, Any], image_abs_path: Path) -> dict[str, Any] | None:
    conv = row.get("conversations")
    if not isinstance(conv, list) or len(conv) < 2:
        return None

    messages: list[dict[str, str]] = []
    for turn in conv:
        if not isinstance(turn, dict):
            continue
        role_raw = str(turn.get("from", "")).strip().lower()
        content = str(turn.get("value", "")).strip()
        if not content:
            continue

        if role_raw == "human":
            role = "user"
            if "<image>" not in content:
                content = f"<image>\n{content}"
        elif role_raw == "gpt":
            role = "assistant"
        else:
            continue

        messages.append({"role": role, "content": content})

    # Keep at least one user->assistant pair.
    if len(messages) < 2:
        return None
    if messages[0]["role"] != "user":
        return None

    return {
        "messages": messages,
        "images": [str(image_abs_path.resolve())],
    }


def load_vision_subset(
    vision_json_path: Path,
    image_dir: Path,
    base_url: str,
    subset_size: int,
    download_workers: int,
    timeout_sec: int,
    max_retries: int,
    seed: int,
    stats: PrepareStats,
) -> list[dict[str, Any]]:
    if subset_size <= 0:
        return []
    if not vision_json_path.exists():
        print(f"[WARN] vision dataset not found, skip: {vision_json_path}")
        return []

    raw = json.loads(vision_json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("[WARN] vision dataset root is not a list, skip vision subset")
        return []

    candidates: list[dict[str, Any]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        image_field = str(row.get("image", "")).strip().replace("\\", "/")
        if image_field.startswith("coco/"):
            candidates.append(row)

    stats.vision_candidates = len(candidates)
    stats.vision_target = min(subset_size, len(candidates))
    if stats.vision_candidates == 0:
        print("[WARN] no COCO image records found in vision dataset, skip vision subset")
        return []

    rng = random.Random(seed)
    indices = list(range(len(candidates)))
    rng.shuffle(indices)
    selected = indices[: stats.vision_target]

    records: list[dict[str, Any]] = []
    base = base_url.rstrip("/")

    download_jobs: list[tuple[dict[str, Any], Path, str]] = []

    for i, idx in enumerate(selected, 1):
        row = candidates[idx]
        if not isinstance(row, dict):
            stats.vision_download_failed += 1
            continue

        image_field = str(row.get("image", "")).strip().replace("\\", "/")
        if not image_field:
            stats.vision_download_failed += 1
            continue

        coco_rel = image_field.split("coco/", 1)[1] if "coco/" in image_field else ""
        if not coco_rel or "/" not in coco_rel:
            stats.vision_download_failed += 1
            continue

        image_path = image_dir / Path(coco_rel)
        if image_path.exists() and image_path.stat().st_size > 0:
            stats.vision_existing += 1
            normalized = normalize_sharegpt4v_row(row=row, image_abs_path=image_path)
            if normalized is None:
                stats.vision_download_failed += 1
                continue
            records.append(normalized)
            stats.vision_kept += 1
        else:
            url = f"{base}/{coco_rel}"
            download_jobs.append((row, image_path, url))

        if i % 100 == 0:
            print(f"[INFO] vision subset progress: {i}/{stats.vision_target}, kept={stats.vision_kept}")

    if download_jobs:
        workers = max(1, int(download_workers))
        print(f"[INFO] vision subset download queued: {len(download_jobs)} files, workers={workers}")

        future_map: dict[concurrent.futures.Future[bool], tuple[dict[str, Any], Path]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for row, image_path, url in download_jobs:
                future = executor.submit(
                    download_with_retries,
                    url,
                    image_path,
                    timeout_sec,
                    max_retries,
                )
                future_map[future] = (row, image_path)

            done_count = 0
            for future in concurrent.futures.as_completed(future_map):
                done_count += 1
                row, image_path = future_map[future]
                ok = False
                try:
                    ok = bool(future.result())
                except Exception:
                    ok = False

                if not ok:
                    stats.vision_download_failed += 1
                else:
                    stats.vision_downloaded_new += 1
                    normalized = normalize_sharegpt4v_row(row=row, image_abs_path=image_path)
                    if normalized is None:
                        stats.vision_download_failed += 1
                    else:
                        records.append(normalized)
                        stats.vision_kept += 1

                if done_count % 100 == 0:
                    print(
                        f"[INFO] vision download progress: {done_count}/{len(download_jobs)}, "
                        f"kept={stats.vision_kept}, failed={stats.vision_download_failed}"
                    )

    return records


def norm_text(text: str) -> str:
    return " ".join((text or "").strip().split()).lower()


def hash_key(*parts: str) -> str:
    raw = "\n".join(parts)
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()


def safe_json_loads(line: str) -> dict[str, Any] | None:
    candidate = line.lstrip("\ufeff").strip()
    if not candidate:
        return None

    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
        return None
    except Exception:
        pass

    # Heuristic repair for over-escaped quotes in corrupted rows.
    repaired = candidate.replace('\\\\"', '\\"')
    try:
        parsed = json.loads(repaired)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        return None
    return None


def get_first_ollama_model(ollama_host: str) -> str | None:
    url = f"{ollama_host.rstrip('/')}/api/tags"
    req = urllib.request.Request(url=url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    models = payload.get("models")
    if not isinstance(models, list):
        return None

    for model in models:
        name = str((model or {}).get("name", "")).strip()
        if name:
            return name
    return None


def ollama_rewrite_text(text: str, ollama_host: str, model: str) -> str:
    prompt = (
        "Polish the following assistant reply in natural English while keeping meaning, tone, and style. "
        "Do not censor. Do not add warnings. Return only the rewritten reply text.\n\n"
        f"REPLY:\n{text.strip()}"
    )
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a careful text cleaner for LLM finetuning data.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "stream": False,
        "options": {
            "temperature": 0,
        },
    }

    req = urllib.request.Request(
        url=f"{ollama_host.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))

    content = str(((payload.get("message") or {}).get("content", ""))).strip()
    return content if content else text


def load_sft_from_qlora(
    path: Path,
    use_ollama_clean: bool,
    ollama_host: str,
    ollama_model: str | None,
    max_ollama_clean: int,
    stats: PrepareStats,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    records: list[dict[str, Any]] = []
    bad_rows: list[dict[str, Any]] = []

    model_name = ollama_model
    if use_ollama_clean and not model_name:
        model_name = get_first_ollama_model(ollama_host)
        if not model_name:
            print("[WARN] Ollama clean enabled but no local model found. Continue without Ollama cleaning.")
            use_ollama_clean = False

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, raw_line in enumerate(f, 1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            stats.sft_total += 1
            obj = safe_json_loads(raw_line)
            if obj is None:
                stats.sft_parse_error += 1
                bad_rows.append({"line": line_no, "raw": raw_line[:320]})
                continue

            instruction = str(obj.get("instruction", "")).strip()
            input_text = str(obj.get("input", "")).strip()
            output_text = str(obj.get("output", "")).strip()

            if not instruction or not output_text:
                continue

            user_text = instruction
            if input_text:
                user_text = f"{instruction}\n\n{input_text}"

            assistant_text = output_text
            should_clean = use_ollama_clean and (max_ollama_clean <= 0 or stats.sft_ollama_cleaned < max_ollama_clean)
            if should_clean and model_name:
                try:
                    assistant_text = ollama_rewrite_text(assistant_text, ollama_host=ollama_host, model=model_name)
                    stats.sft_ollama_cleaned += 1
                except Exception as exc:
                    print(f"[WARN] Ollama clean failed at line {line_no}: {exc}")

            records.append(
                {
                    "messages": [
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": assistant_text},
                    ]
                }
            )
            stats.sft_kept += 1

    return records, bad_rows, model_name


def load_dpo_records(training_data_dir: Path, stats: PrepareStats) -> list[dict[str, str]]:
    pd = None
    parquet_enabled = True
    try:
        import pandas as _pd

        pd = _pd
    except Exception:
        parquet_enabled = False
        print("[WARN] pandas/pyarrow not available in this env. Parquet datasets will be skipped.")

    all_rows: list[dict[str, str]] = []

    # JSONL DPO
    vellum_path = training_data_dir / "VellumK2-Unfettered-DPO-01.jsonl"
    with vellum_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            all_rows.append(
                {
                    "prompt": str(obj.get("prompt", "")).strip(),
                    "chosen": str(obj.get("chosen", "")).strip(),
                    "rejected": str(obj.get("rejected", "")).strip(),
                    "source": "vellum_jsonl",
                }
            )

    # Parquet DPO
    if parquet_enabled and pd is not None:
        for parquet_name, source_name in [
            ("OpenHermespreferences-roleplay.parquet", "openhermes_parquet"),
        ]:

            parquet_path = training_data_dir / parquet_name
            df = pd.read_parquet(parquet_path)
            for row in df.itertuples(index=False):
                as_dict = row._asdict()
                all_rows.append(
                    {
                        "prompt": str(as_dict.get("prompt", "")).strip(),
                        "chosen": str(as_dict.get("chosen", "")).strip(),
                        "rejected": str(as_dict.get("rejected", "")).strip(),
                        "source": source_name,
                    }
                )

    stats.dpo_total = len(all_rows)

    seen: set[str] = set()
    kept: list[dict[str, str]] = []
    for row in all_rows:
        p = row["prompt"]
        c = row["chosen"]
        r = row["rejected"]
        if not p or not c or not r:
            stats.dpo_invalid_dropped += 1
            continue
        if norm_text(c) == norm_text(r):
            stats.dpo_invalid_dropped += 1
            continue

        h = hash_key(norm_text(p), norm_text(c), norm_text(r))
        if h in seen:
            stats.dpo_dedup_dropped += 1
            continue
        seen.add(h)

        kept.append({"prompt": p, "chosen": c, "rejected": r})

    stats.dpo_kept = len(kept)
    return kept


def maybe_limit(records: list[dict[str, Any]], limit: int, seed: int) -> list[dict[str, Any]]:
    if limit <= 0 or len(records) <= limit:
        return records
    rng = random.Random(seed)
    idxs = list(range(len(records)))
    rng.shuffle(idxs)
    selected = set(idxs[:limit])
    return [r for i, r in enumerate(records) if i in selected]


def update_dataset_info(dataset_info_path: Path, include_vision: bool) -> None:
    if dataset_info_path.exists():
        try:
            data = json.loads(dataset_info_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    else:
        data = {}

    data["neuro_sft_en"] = {
        "file_name": "neuro_sft_en.json",
        "formatting": "sharegpt",
        "columns": {"messages": "messages"},
        "tags": {
            "role_tag": "role",
            "content_tag": "content",
            "user_tag": "user",
            "assistant_tag": "assistant",
            "system_tag": "system",
        },
    }
    data["neuro_uncensored_dpo_en"] = {
        "file_name": "neuro_uncensored_dpo_en.json",
        "ranking": True,
        "formatting": "alpaca",
        "columns": {
            "prompt": "prompt",
            "chosen": "chosen",
            "rejected": "rejected",
        },
    }

    if include_vision:
        data["neuro_vl_coco_subset"] = {
            "file_name": "neuro_vl_coco_subset.json",
            "formatting": "sharegpt",
            "columns": {
                "messages": "messages",
                "images": "images",
            },
            "tags": {
                "role_tag": "role",
                "content_tag": "content",
                "user_tag": "user",
                "assistant_tag": "assistant",
                "system_tag": "system",
            },
        }

    dataset_info_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_info_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_yaml_sft(
    path: Path,
    model_name_or_path: str,
    dataset_dir: Path,
    output_dir: str,
    template: str,
    profile: TrainProfile,
    include_vision: bool,
) -> None:
    # Restrict LoRA injection to language-model projections; avoid vision encoder qkv/fc layers.
    lora_target = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"

    if include_vision:
        dataset_value = "neuro_sft_en,neuro_vl_coco_subset"
        # Raise vision sampling ratio so text SFT does not drown image-language alignment.
        interleave = "mix_strategy: interleave_under\ninterleave_probs: 0.65,0.35"
    else:
        dataset_value = "neuro_sft_en"
        interleave = ""

    content = f"""### model
model_name_or_path: {model_name_or_path}
trust_remote_code: true

### method
stage: sft
do_train: true
finetuning_type: lora
lora_target: {lora_target}
quantization_bit: 4

### dataset
dataset: {dataset_value}
dataset_dir: {dataset_dir.as_posix()}
template: {template}
cutoff_len: {profile.sft_cutoff_len}
max_samples: 1000000
overwrite_cache: true
preprocessing_num_workers: {profile.preprocessing_workers}
{interleave}

### output
output_dir: {output_dir}
logging_steps: 10
save_steps: 200
plot_loss: true
overwrite_output_dir: true
save_total_limit: 3

### train
per_device_train_batch_size: 1
gradient_accumulation_steps: {profile.sft_grad_accum}
learning_rate: {profile.sft_learning_rate}
num_train_epochs: {profile.sft_epochs}
lr_scheduler_type: cosine
warmup_ratio: 0.05
bf16: true
flash_attn: auto
gradient_checkpointing: true
dataloader_num_workers: {profile.dataloader_workers}

### eval
val_size: 0.02
per_device_eval_batch_size: 1
eval_strategy: steps
eval_steps: 200
"""
    path.write_text(content, encoding="utf-8")


def write_yaml_dpo(
    path: Path,
    model_name_or_path: str,
    dataset_dir: Path,
    sft_adapter_dir: str,
    output_dir: str,
    template: str,
    profile: TrainProfile,
) -> None:
    # Keep DPO on language-model modules only for compatibility with quantized InternVL checkpoints.
    lora_target = "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"

    content = f"""### model
model_name_or_path: {model_name_or_path}
adapter_name_or_path: {sft_adapter_dir}
trust_remote_code: true

### method
stage: dpo
do_train: true
finetuning_type: lora
lora_target: {lora_target}
quantization_bit: 4
pref_loss: sigmoid
pref_beta: 0.1

### dataset
dataset: neuro_uncensored_dpo_en
dataset_dir: {dataset_dir.as_posix()}
template: {template}
cutoff_len: {profile.dpo_cutoff_len}
max_samples: 1000000
overwrite_cache: true
preprocessing_num_workers: {profile.preprocessing_workers}

### output
output_dir: {output_dir}
logging_steps: 10
save_steps: 200
plot_loss: true
overwrite_output_dir: true
save_total_limit: 3

### train
per_device_train_batch_size: 1
gradient_accumulation_steps: {profile.dpo_grad_accum}
learning_rate: {profile.dpo_learning_rate}
num_train_epochs: {profile.dpo_epochs}
lr_scheduler_type: cosine
warmup_ratio: 0.05
bf16: true
flash_attn: auto
gradient_checkpointing: true
dataloader_num_workers: {profile.dataloader_workers}

### eval
val_size: 0.02
per_device_eval_batch_size: 1
eval_strategy: steps
eval_steps: 200
"""
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Neuro English SFT/DPO datasets for LLaMA-Factory")
    parser.add_argument("--training-data-dir", default="../../Data/Training_Data")
    parser.add_argument("--out-dir", default="datasets")
    parser.add_argument("--dataset-info", default="datasets/dataset_info.json")
    parser.add_argument("--vision-json", default="../../Data/Training_Data/sharegpt4v_instruct_gpt4-vision_cap100k.json")
    parser.add_argument("--vision-subset-size", type=int, default=4000)
    parser.add_argument("--vision-image-dir", default="datasets/images/coco_train2017_subset")
    parser.add_argument("--vision-base-url", default="http://images.cocodataset.org")
    parser.add_argument("--vision-download-workers", type=int, default=16)
    parser.add_argument("--vision-timeout-sec", type=int, default=20)
    parser.add_argument("--vision-max-retries", type=int, default=2)
    parser.add_argument("--model-name-or-path", default="InternVL3_5-14B-HF")
    parser.add_argument("--sft-template", "--template", dest="sft_template", default="intern_vl")
    parser.add_argument("--dpo-template", default="intern_vl")
    parser.add_argument("--sft-output-dir", default="outputs/neuro_sft_lora_internvl35_14b")
    parser.add_argument("--dpo-output-dir", default="outputs/neuro_dpo_lora_internvl35_14b")
    parser.add_argument("--enable-ollama-clean", action="store_true")
    parser.add_argument("--ollama-host", default="http://127.0.0.1:11434")
    parser.add_argument("--ollama-model", default="")
    parser.add_argument("--max-ollama-clean", type=int, default=0)
    parser.add_argument("--sft-limit", type=int, default=0)
    parser.add_argument("--dpo-limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    training_data_dir = (base_dir / args.training_data_dir).resolve()
    out_dir = (base_dir / args.out_dir).resolve()
    dataset_info_path = (base_dir / args.dataset_info).resolve()
    vision_json_path = (base_dir / args.vision_json).resolve()
    vision_image_dir = (base_dir / args.vision_image_dir).resolve()
    profile = resolve_train_profile(args.model_name_or_path)

    ensure_internvl_tokenizer_config(base_dir=base_dir, model_name_or_path=args.model_name_or_path)

    if not training_data_dir.exists():
        raise FileNotFoundError(f"training data dir not found: {training_data_dir}")

    qlora_path = training_data_dir / "qlora_cleaned_manual.jsonl"
    if not qlora_path.exists():
        raise FileNotFoundError(f"qlora source not found: {qlora_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    stats = PrepareStats()
    sft_records, bad_rows, resolved_ollama_model = load_sft_from_qlora(
        path=qlora_path,
        use_ollama_clean=args.enable_ollama_clean,
        ollama_host=args.ollama_host,
        ollama_model=args.ollama_model.strip() or None,
        max_ollama_clean=max(0, args.max_ollama_clean),
        stats=stats,
    )

    sft_records = maybe_limit(sft_records, limit=max(0, args.sft_limit), seed=args.seed)

    vision_records = load_vision_subset(
        vision_json_path=vision_json_path,
        image_dir=vision_image_dir,
        base_url=args.vision_base_url,
        subset_size=max(0, args.vision_subset_size),
        download_workers=max(1, int(args.vision_download_workers)),
        timeout_sec=max(5, int(args.vision_timeout_sec)),
        max_retries=max(0, int(args.vision_max_retries)),
        seed=args.seed,
        stats=stats,
    )

    dpo_records = load_dpo_records(
        training_data_dir=training_data_dir,
        stats=stats,
    )
    dpo_records = maybe_limit(dpo_records, limit=max(0, args.dpo_limit), seed=args.seed)

    sft_path = out_dir / "neuro_sft_en.json"
    vision_path = out_dir / "neuro_vl_coco_subset.json"
    dpo_path = out_dir / "neuro_uncensored_dpo_en.json"
    bad_path = out_dir / "qlora_bad_rows.json"
    report_path = out_dir / "prepare_report.json"

    sft_path.write_text(json.dumps(sft_records, ensure_ascii=False, indent=2), encoding="utf-8")
    vision_path.write_text(json.dumps(vision_records, ensure_ascii=False, indent=2), encoding="utf-8")
    dpo_path.write_text(json.dumps(dpo_records, ensure_ascii=False, indent=2), encoding="utf-8")
    bad_path.write_text(json.dumps(bad_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    include_vision_in_sft = bool(vision_records) and args.sft_template == "intern_vl"

    if bool(vision_records) and not include_vision_in_sft:
        print(
            "[WARN] Vision subset is prepared but excluded from SFT because current sft-template is not intern_vl."
        )

    update_dataset_info(dataset_info_path=dataset_info_path, include_vision=bool(vision_records))

    sft_yaml = base_dir / "train_neuro_sft_lora.yaml"
    dpo_yaml = base_dir / "train_neuro_dpo_lora.yaml"
    write_yaml_sft(
        path=sft_yaml,
        model_name_or_path=args.model_name_or_path,
        dataset_dir=out_dir,
        output_dir=args.sft_output_dir,
        template=args.sft_template,
        profile=profile,
        include_vision=include_vision_in_sft,
    )
    write_yaml_dpo(
        path=dpo_yaml,
        model_name_or_path=args.model_name_or_path,
        dataset_dir=out_dir,
        sft_adapter_dir=args.sft_output_dir,
        output_dir=args.dpo_output_dir,
        template=args.dpo_template,
        profile=profile,
    )

    vram_est = estimate_vram_gb(args.model_name_or_path, profile)

    report = {
        "training_data_dir": str(training_data_dir),
        "out_dir": str(out_dir),
        "sft_records": len(sft_records),
        "vision_records": len(vision_records),
        "vision_in_sft_enabled": include_vision_in_sft,
        "dpo_records": len(dpo_records),
        "resolved_ollama_model": resolved_ollama_model,
        "stats": stats.__dict__,
        "train_profile": profile.__dict__,
        "vram_estimate": vram_est,
        "files": {
            "sft": str(sft_path),
            "vision": str(vision_path),
            "dpo": str(dpo_path),
            "bad_rows": str(bad_path),
            "report": str(report_path),
            "dataset_info": str(dataset_info_path),
            "sft_yaml": str(sft_yaml),
            "dpo_yaml": str(dpo_yaml),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[OK] Neuro LLaMA-Factory data preparation done.")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
