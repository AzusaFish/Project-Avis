import json
import inspect
import os
import time
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "1800")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "120")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")

import torch
from datasets import Dataset
from huggingface_hub import snapshot_download
from tqdm.auto import tqdm
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
from transformers import TrainingArguments
from trl import SFTTrainer


DATA_FILE = Path("Data/qlora_cleaned_manual.jsonl")
MODEL_NAME = "unsloth/Qwen2.5-14B-Instruct-bnb-4bit"
OUTPUT_DIR = "outputs"
LORA_DIR = "avis_lora_model"
MODEL_CACHE_DIR = Path("hf_cache")


def load_instruction_dataset(path: Path) -> Dataset:
    if not path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    rows = []
    bad_lines = []
    all_lines = path.read_text(encoding="utf-8-sig").splitlines()
    for i, line in tqdm(
        enumerate(all_lines, 1),
        total=len(all_lines),
        desc="Loading JSONL",
        unit="line",
    ):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception as exc:
            bad_lines.append((i, str(exc)))
            continue

        instruction = str(obj.get("instruction", "")).strip()
        user_input = str(obj.get("input", "")).strip()
        output = str(obj.get("output", "")).strip()
        if not instruction or not output:
            continue

        user_text = instruction if not user_input else f"{instruction}\n\nInput:\n{user_input}"
        rows.append(
            {
                "messages": [
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": output},
                ]
            }
        )

    if bad_lines:
        preview = ", ".join(f"line {ln} ({err})" for ln, err in bad_lines[:8])
        raise ValueError(
            "Dataset contains malformed JSON lines. "
            f"Count={len(bad_lines)}. Examples: {preview}"
        )
    if not rows:
        raise ValueError("No valid samples found in dataset after filtering.")

    print(f"Loaded {len(rows)} valid samples from {path}")
    return Dataset.from_list(rows)


def get_training_profile() -> dict[str, int]:
    """Return conservative hyper-parameters based on detected GPU memory."""
    if not torch.cuda.is_available():
        return {
            "max_seq_length": 512,
            "lora_r": 8,
            "batch_size": 1,
            "grad_accum": 16,
        }

    vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    # 16 GB cards are memory-constrained for Qwen2.5-14B even with 4-bit + LoRA.
    if vram_gb <= 16.5:
            return {
                "max_seq_length": 1024,
                "lora_r": 64, 
                "batch_size": 1,
                "grad_accum": 16,
            }
    if vram_gb <= 24.5:
        return {
            "max_seq_length": 1536,
            "lora_r": 64,
            "batch_size": 1,
            "grad_accum": 16,
        }
    return {
        "max_seq_length": 2048,
        "lora_r": 64,
        "batch_size": 2,
        "grad_accum": 8,
        }


def ensure_model_downloaded(repo_id: str, retries: int = 8) -> str:
    """Download model snapshot robustly and return local path."""
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, retries + 1):
        try:
            print(f"Ensuring model files are cached (attempt {attempt}/{retries})...")
            local_path = snapshot_download(
                repo_id=repo_id,
                cache_dir=str(MODEL_CACHE_DIR),
                local_files_only=False,
                resume_download=True,
                max_workers=1,
                etag_timeout=120,
            )
            print(f"Model cache ready: {local_path}")
            return local_path
        except Exception as exc:
            if attempt == retries:
                raise RuntimeError(
                    "Model download failed repeatedly due to network instability. "
                    "Please rerun the same command to continue resume-download. "
                    f"Last error: {exc}"
                ) from exc
            wait_s = min(120, 5 * attempt)
            print(f"Download failed: {exc}")
            print(f"Retrying in {wait_s}s...")
            time.sleep(wait_s)

    raise RuntimeError("Unexpected downloader exit")


def build_training_args_kwargs(*, profile: dict[str, int], bf16_ok: bool) -> dict:
    """Build TrainingArguments kwargs compatible with installed transformers version."""
    kwargs = {
        "per_device_train_batch_size": profile["batch_size"],
        "gradient_accumulation_steps": profile["grad_accum"],
        "warmup_steps": 5,
        "max_steps": 60,
        "learning_rate": 2e-4,
        "fp16": not bf16_ok,
        "bf16": bf16_ok,
        "logging_steps": 1,
        "optim": "adamw_8bit",
        "weight_decay": 0.01,
        "lr_scheduler_type": "linear",
        "seed": 3407,
        "output_dir": OUTPUT_DIR,
        "auto_find_batch_size": True,
        "gradient_checkpointing": True,
        "dataloader_pin_memory": False,
        "report_to": "none",
        "disable_tqdm": False,
    }

    supported = inspect.signature(TrainingArguments.__init__).parameters
    if "group_by_length" in supported:
        kwargs["group_by_length"] = True

    return kwargs


def main() -> None:
    profile = get_training_profile()
    max_seq_length = profile["max_seq_length"]
    dtype = torch.bfloat16
    load_in_4bit = True

    print("Training profile:")
    print(f"- max_seq_length={max_seq_length}")
    print(f"- lora_r={profile['lora_r']}")
    print(f"- per_device_train_batch_size={profile['batch_size']}")
    print(f"- gradient_accumulation_steps={profile['grad_accum']}")

    model_source = ensure_model_downloaded(MODEL_NAME)
    print("Loading Qwen2.5-14B Base Model in 4-bit...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_source,
        max_seq_length=max_seq_length,
        dtype=dtype,
        load_in_4bit=load_in_4bit,
    )

    print("Injecting LoRA adapters...")
    model = FastLanguageModel.get_peft_model(
        model,
        r=profile["lora_r"],
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=3407,
        use_rslora=False,
        loftq_config=None,
    )

    print("Preparing dataset...")
    tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
    dataset = load_instruction_dataset(DATA_FILE)

    def formatting_prompts_func(examples):
        convos = examples["messages"]
        texts = [
            tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=False)
            for convo in convos
        ]
        return {"text": texts}

    dataset = dataset.map(formatting_prompts_func, batched=True)

    bf16_ok = torch.cuda.is_available() and torch.cuda.is_bf16_supported()
    print(f"CUDA available={torch.cuda.is_available()}, bf16={bf16_ok}")
    training_args_kwargs = build_training_args_kwargs(profile=profile, bf16_ok=bf16_ok)

    print("Initializing SFT Trainer...")
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=max_seq_length,
        dataset_num_proc=2,
        packing=False,
        args=TrainingArguments(**training_args_kwargs),
    )

    print("Starting training phase.")
    trainer.train()

    print("Training complete. Saving LoRA weights...")
    model.save_pretrained(LORA_DIR)
    tokenizer.save_pretrained(LORA_DIR)
    print("Success! LoRA saved.")


if __name__ == "__main__":
    main()