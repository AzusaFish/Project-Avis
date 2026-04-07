# import logging
# import os
# import re
# import subprocess
# from pathlib import Path

# import torch
# from peft import PeftModel
# from transformers import AutoModelForCausalLM, AutoTokenizer

# os.environ.setdefault("HF_HUB_OFFLINE", "1")
# os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# ROOT = Path(__file__).resolve().parent
# LORA_DIR = ROOT / "avis_lora_model"
# EXPORT_ROOT = ROOT / "exports"
# MODEL_STEM = "Avis-14B-v1"
# MERGED_DIR = EXPORT_ROOT / f"{MODEL_STEM}-merged-16bit"
# GGUF_PREFIX = EXPORT_ROOT / "gguf" / MODEL_STEM
# FULL_BASE_REPO_DIR = ROOT / "hf_cache" / "models--Qwen--Qwen2.5-14B-Instruct" / "snapshots"
# EXPORT_LOG = EXPORT_ROOT / "export.log"
# LLAMA_CPP_DIR = Path.home() / ".unsloth" / "llama.cpp"


# def setup_logger() -> logging.Logger:
#     EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
#     logger = logging.getLogger("avis_export")
#     logger.setLevel(logging.INFO)
#     logger.handlers.clear()

#     formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

#     fh = logging.FileHandler(EXPORT_LOG, encoding="utf-8")
#     fh.setFormatter(formatter)
#     logger.addHandler(fh)

#     sh = logging.StreamHandler()
#     sh.setFormatter(formatter)
#     logger.addHandler(sh)
#     return logger


# def find_full_base_snapshot() -> Path:
#     if not FULL_BASE_REPO_DIR.exists():
#         raise FileNotFoundError(
#             "Full base snapshot root missing: "
#             f"{FULL_BASE_REPO_DIR}"
#         )

#     candidates = sorted([p for p in FULL_BASE_REPO_DIR.iterdir() if p.is_dir()])
#     for p in reversed(candidates):
#         if (p / "config.json").exists() and (
#             (p / "model.safetensors.index.json").exists() or any(p.glob("model*.safetensors"))
#         ):
#             return p
#     raise FileNotFoundError(f"No valid snapshot under {FULL_BASE_REPO_DIR}")


# def ensure_merged_model_exists(merged_dir: Path) -> None:
#     config_ok = (merged_dir / "config.json").exists()
#     has_weights = any(merged_dir.glob("model*.safetensors")) or any(merged_dir.glob("pytorch_model*.bin"))
#     if not (config_ok and has_weights):
#         raise RuntimeError(f"Merged model missing files in {merged_dir}")


# def find_converter_script() -> Path:
#     candidates = [
#         LLAMA_CPP_DIR / "unsloth_convert_hf_to_gguf.py",
#         LLAMA_CPP_DIR / "convert_hf_to_gguf.py",
#     ]
#     for p in candidates:
#         if p.exists():
#             return p
#     raise FileNotFoundError("No GGUF converter script found in local llama.cpp folder")


# def find_quantizer_exe() -> Path:
#     candidates = [
#         LLAMA_CPP_DIR / "llama-quantize.exe",
#         LLAMA_CPP_DIR / "build" / "bin" / "Release" / "llama-quantize.exe",
#     ]
#     for p in candidates:
#         if p.exists():
#             return p
#     raise FileNotFoundError("No llama-quantize.exe found in local llama.cpp folder")


# def run_converter(converter_path: Path, input_dir: Path, output_file: Path, logger: logging.Logger) -> list[Path]:
#     cmd = [
#         os.sys.executable,
#         str(converter_path),
#         "--outfile",
#         str(output_file),
#         "--outtype",
#         "f16",
#         "--split-max-size",
#         "50G",
#         str(input_dir),
#     ]
#     logger.info("Running converter: %s", " ".join(cmd))
#     result = subprocess.run(cmd, text=True, capture_output=True)
#     if result.stdout:
#         logger.info(result.stdout.rstrip())
#     if result.returncode != 0:
#         if result.stderr:
#             logger.error(result.stderr.rstrip())
#         raise RuntimeError(f"convert_hf_to_gguf failed with exit code {result.returncode}")

#     if output_file.exists():
#         return [output_file]

#     # Handle sharded output: <name>.F16-00001-of-000NN.gguf
#     pattern = re.compile(rf"^{re.escape(output_file.stem)}-(\d{{5}})-of-(\d{{5}})\.gguf$", re.IGNORECASE)
#     parent = output_file.parent
#     shards = sorted([p for p in parent.glob("*.gguf") if pattern.match(p.name)])
#     if not shards:
#         raise RuntimeError("No GGUF output found after conversion")
#     return shards


# def run_quantize(quantizer: Path, input_gguf: Path, output_gguf: Path, logger: logging.Logger) -> None:
#     n_threads = max((os.cpu_count() or 1) * 2, 1)
#     cmd = [str(quantizer), str(input_gguf), str(output_gguf), "q4_k_m", str(n_threads)]
#     logger.info("Running quantizer: %s", " ".join(cmd))
#     result = subprocess.run(cmd, text=True, capture_output=True)
#     if result.stdout:
#         logger.info(result.stdout.rstrip())
#     if result.returncode != 0:
#         if result.stderr:
#             logger.error(result.stderr.rstrip())
#         raise RuntimeError(f"llama-quantize failed with exit code {result.returncode}")
#     if not output_gguf.exists():
#         raise RuntimeError(f"Quantized file not created: {output_gguf}")


# def main() -> None:
#     logger = setup_logger()
#     logger.info("Starting export pipeline")

#     if not LORA_DIR.exists():
#         raise FileNotFoundError(f"LoRA directory missing: {LORA_DIR}")

#     base_snapshot = find_full_base_snapshot()
#     logger.info("Using base snapshot: %s", base_snapshot)
#     logger.info("Using LoRA adapter: %s", LORA_DIR)

#     logger.info("Loading tokenizer")
#     try:
#         tokenizer = AutoTokenizer.from_pretrained(str(LORA_DIR), local_files_only=True)
#     except Exception:
#         tokenizer = AutoTokenizer.from_pretrained(str(base_snapshot), local_files_only=True)

#     logger.info("Loading base model on CPU with low_cpu_mem_usage")
#     base_model = AutoModelForCausalLM.from_pretrained(
#         str(base_snapshot),
#         torch_dtype=torch.float16,
#         device_map="cpu",
#         low_cpu_mem_usage=True,
#         local_files_only=True,
#     )

#     logger.info("Loading LoRA adapter onto base model")
#     peft_model = PeftModel.from_pretrained(
#         base_model,
#         str(LORA_DIR),
#         is_trainable=False,
#         local_files_only=True,
#     )

#     logger.info("Merging LoRA into base model")
#     merged_model = peft_model.merge_and_unload(progressbar=True)

#     logger.info("Saving merged 16-bit model to %s", MERGED_DIR)
#     MERGED_DIR.mkdir(parents=True, exist_ok=True)
#     merged_model.save_pretrained(
#         str(MERGED_DIR),
#         safe_serialization=True,
#         max_shard_size="5GB",
#     )
#     tokenizer.save_pretrained(str(MERGED_DIR))
#     ensure_merged_model_exists(MERGED_DIR)

#     logger.info("Converting merged model to F16 GGUF")
#     (EXPORT_ROOT / "gguf").mkdir(parents=True, exist_ok=True)
#     converter_path = find_converter_script()
#     f16_out = GGUF_PREFIX.with_suffix(".F16.gguf")
#     gguf_files = run_converter(converter_path, MERGED_DIR, f16_out, logger)
#     f16_gguf = gguf_files[0]

#     quantizer = find_quantizer_exe()
#     q4_path = f16_gguf.with_name(f"{MODEL_STEM}.Q4_K_M.gguf")
#     logger.info("Quantizing with %s", quantizer)
#     run_quantize(quantizer, f16_gguf, q4_path, logger)

#     logger.info("Export complete")
#     logger.info("F16 GGUF: %s", f16_gguf)
#     logger.info("Q4_K_M GGUF: %s", q4_path)


# if __name__ == "__main__":
#     main()

import os
import logging
from pathlib import Path
import torch
from unsloth import FastLanguageModel
from tqdm import tqdm

os.environ.setdefault("HF_HUB_OFFLINE", "1")

# --- 核心路径配置 ---
ROOT = Path(__file__).resolve().parent
LORA_DIR = ROOT / "avis_lora_model"
EXPORT_ROOT = ROOT / "exports"
MODEL_STEM = "Avis-14B-v1"
LOG_FILE = EXPORT_ROOT / "export.log"

# 指向你刚才下好模型的那个自定义缓存目录
CACHE_DIR = ROOT / "hf_cache"
FULL_BASE_REPO_DIR = CACHE_DIR / "models--Qwen--Qwen2.5-14B-Instruct" / "snapshots"

def find_full_base_snapshot() -> Path:
    """精准定位本地下载好的模型快照绝对路径"""
    if not FULL_BASE_REPO_DIR.exists():
        raise FileNotFoundError(f"找不到基础模型目录: {FULL_BASE_REPO_DIR}")
    
    candidates = sorted([p for p in FULL_BASE_REPO_DIR.iterdir() if p.is_dir()])
    for p in reversed(candidates):
        if (p / "config.json").exists():
            return p
    raise FileNotFoundError("在缓存中没有找到完整的模型快照！")

def setup_logger():
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("avis_export")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    class TqdmLoggingHandler(logging.Handler):
        def emit(self, record):
            try:
                msg = self.format(record)
                tqdm.write(msg)
                self.flush()
            except Exception:
                self.handleError(record)

    sh = TqdmLoggingHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    return logger

def main():
    logger = setup_logger()
    logger.info("Starting safe export pipeline using Unsloth engine.")
    steps = ["Locate Snapshot", "Load Base Model", "Inject LoRA", "Export to GGUF"]
    pbar = tqdm(total=len(steps), desc="Overall Progress", unit="step")

    try:
        # Step 0: 定位绝对路径
        snapshot_path = find_full_base_snapshot()
        logger.info(f"Step 0: Found base model at {snapshot_path}")
        pbar.update(1)

        # Step 1: 加载基础模型 (直接传入绝对路径，杜绝迷路)
        logger.info("Step 1: Loading base model in 16-bit format...")
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=str(snapshot_path), # <--- 强行指定本地绝对路径
            max_seq_length=2048,
            dtype=torch.float16,
            load_in_4bit=False,
            local_files_only=True
        )
        pbar.update(1)

        # Step 2: 注入 LoRA
        logger.info(f"Step 2: Loading LoRA adapter from {LORA_DIR}...")
        model.load_adapter(str(LORA_DIR))
        pbar.update(1)

        # Step 3: 底层合并与导出
        logger.info("Step 3: Exporting to Q4_K_M GGUF format. This will take some time...")
        model.save_pretrained_gguf(
            save_directory=str(EXPORT_ROOT / MODEL_STEM),
            tokenizer=tokenizer,
            quantization_method="q4_k_m",
        )
        pbar.update(1)

        logger.info("✅ Export completed successfully! Check the 'exports' directory.")

    except Exception as e:
        logger.error(f"❌ Export pipeline failed: {str(e)}", exc_info=True)
        raise
    finally:
        pbar.close()

if __name__ == "__main__":
    main()