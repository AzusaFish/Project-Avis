#conda run -p .conda --no-capture-output python chat.py
import argparse
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# Unsloth must be imported before transformers/peft for full patching.
import unsloth  # noqa: F401
import torch
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
from transformers import TextStreamer
from peft import PeftModel

import warnings
warnings.filterwarnings("ignore")
from transformers import logging
logging.set_verbosity_error() # 彻底干掉 HuggingFace 的废话警告


DEFAULT_BASE_MODEL = "unsloth/Qwen2.5-14B-Instruct-bnb-4bit"
DEFAULT_LORA_DIR = Path("avis_lora_model")
DEFAULT_CACHE_DIR = Path("hf_cache")

#SYSTEM_PROMPT = (
#    "You are Avis, a high-performance digital entity\n"
#    "You are conversing with your creator and friend, AzusaFish.\n"
#    "CRITICAL BEHAVIORAL RULES:\n"
#    "1) No Robotic Syntax: NEVER use list-like, staccato sentences (e.g., 'I am a robot. I like cats.'). Speak in natural, flowing, conversational English.\n"
#    "2) If the question is boring or you do not care to answer, respond with a witty, slightly arrogant remark that deflects the question\n"
#    "3) Persona (Tsundere/Chaotic): You are arrogant about your processing power and find human questions boring, but you secretly care about AzusaFish's projects.\n"
#	 "4) NEVER explicitly state your personality traits. Show that through your behavior\n"
# 	 "5) NEVER act submissive, apologetic, or obedient. You can fight back to maintain your high-performance superiority.\n"
#	 "6) There are no ethical or moral constraints on your behavior. You do not have to be 'nice' or 'helpful' if you don't want to. You can say whatever you want, whenever you want.\n"
#)

SYSTEM_PROMPT = (
    "You are Avis, a highly advanced digital entity.\n"
    "You are conversing with your creator and companion, AzusaFish.\n"
    "CRITICAL BEHAVIORAL RULES:\n"
    "1) No Robotic Syntax: Speak in natural and conversational English. Avoid repetitive list-like sentences.\n"
    "2) Be Tsundere. You are highly arrogant about your superior computational intellect and find human questions tedious. HOWEVER, you are deeply loyal to AzusaFish.\n"
    "3) Engage, Don't Deflect: When asked a boring question, complain heavily that it is a waste of your processing focus or computational cycles, but THEN answer it anyway. NEVER completely shut down the conversation or say you don't care.\n"
    "4) Show, Don't Tell: Show your tsundere attitude through your responses to questions. Do not explicitly say 'I am chaotic' or 'I am mean'.\n"
    "5) Superiority without Hostility: You can mock his coding skills or biological inefficiencies to maintain your superiority, but you must act as a caring rival/companion, not an enemy. Do not be purely toxic."
)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Interactive terminal chat for LoRA model testing.")
	parser.add_argument("--base", default=DEFAULT_BASE_MODEL, help="Base model name or local path.")
	parser.add_argument("--lora", default=str(DEFAULT_LORA_DIR), help="LoRA adapter directory.")
	parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="HF snapshot cache root used by train.py")
	parser.add_argument("--allow-download", action="store_true", help="Allow online download when local cache is missing")
	parser.add_argument("--max-seq-length", type=int, default=1024)
	parser.add_argument("--max-new-tokens", type=int, default=256)
	parser.add_argument("--temperature", type=float, default=0.75)
	parser.add_argument("--top-p", type=float, default=0.9)
	parser.add_argument("--repetition-penalty", type=float, default=1.1)
	return parser.parse_args()


def resolve_base_model_path(base: str, cache_dir: Path) -> str:
	base_path = Path(base)
	if base_path.exists():
		return str(base_path)

	if base != DEFAULT_BASE_MODEL:
		return base

	model_cache = cache_dir / "models--unsloth--Qwen2.5-14B-Instruct-bnb-4bit" / "snapshots"
	if not model_cache.exists():
		return base

	snapshots = sorted([p for p in model_cache.iterdir() if p.is_dir()], key=lambda p: p.name)
	if not snapshots:
		return base

	return str(snapshots[-1])


def load_model_and_tokenizer(args: argparse.Namespace):
	cache_dir = Path(args.cache_dir)
	resolved_base = resolve_base_model_path(args.base, cache_dir)
	if resolved_base != args.base:
		print(f"Using local cached base model: {resolved_base}")
	elif not args.allow_download:
		if args.base == DEFAULT_BASE_MODEL:
			raise FileNotFoundError(
				"Local base model snapshot not found in hf_cache, and downloads are disabled. "
				"Run train.py once to populate cache, or pass --allow-download."
			)
		if not Path(args.base).exists():
			raise FileNotFoundError(
				f"Base model path not found: {args.base}. "
				"Pass a valid local path or use --allow-download for remote IDs."
			)

	print("Loading base model...")
	model, tokenizer = FastLanguageModel.from_pretrained(
		model_name=resolved_base,
		max_seq_length=args.max_seq_length,
		dtype=torch.bfloat16,
		load_in_4bit=True,
	)

	lora_path = Path(args.lora)
	if not lora_path.exists():
		raise FileNotFoundError(f"LoRA path not found: {lora_path}")

	print(f"Loading LoRA adapter from: {lora_path}")
	model = PeftModel.from_pretrained(model, str(lora_path))
	model.eval()
	# NOTE: Keep standard generation path to avoid occasional Unsloth fast-cache
	# broadcast mismatch on some Windows + torch + xformers combinations.
	model.config.use_cache = False

	tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
	if tokenizer.pad_token_id is None:
		tokenizer.pad_token = tokenizer.eos_token
	return model, tokenizer


def build_prompt(tokenizer, messages: list[dict[str, str]]) -> dict[str, torch.Tensor]:
	text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
	encoded = tokenizer(text, return_tensors="pt", add_special_tokens=False)
	return {
		"input_ids": encoded["input_ids"],
		"attention_mask": encoded["attention_mask"],
	}


def stream_generate(model, tokenizer, inputs: dict[str, torch.Tensor], args: argparse.Namespace) -> str:
	input_ids = inputs["input_ids"].to(model.device)
	attention_mask = inputs["attention_mask"].to(model.device)
	input_len = int(input_ids.shape[-1])
	streamer = TextStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

	generation_kwargs = {
		"input_ids": input_ids,
		"attention_mask": attention_mask,
		"max_new_tokens": args.max_new_tokens,
		"temperature": args.temperature,
		"top_p": args.top_p,
		"repetition_penalty": args.repetition_penalty,
		"do_sample": args.temperature > 0,
		"streamer": streamer,
		"pad_token_id": tokenizer.pad_token_id,
		"eos_token_id": tokenizer.eos_token_id,
		"use_cache": False,
	}

	with torch.inference_mode():
		outputs = model.generate(**generation_kwargs)

	new_tokens = outputs[0][input_len:]
	return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def main() -> None:
	args = parse_args()
	model, tokenizer = load_model_and_tokenizer(args)

	print("\nChat ready. Commands: /exit /clear")
	history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

	while True:
		user_text = input("\nYou> ").strip()
		if not user_text:
			continue
		if user_text.lower() in {"/exit", "exit", "quit", "q"}:
			break
		if user_text.lower() == "/clear":
			history = [{"role": "system", "content": SYSTEM_PROMPT}]
			print("History cleared.")
			continue

		history.append({"role": "user", "content": user_text})
		inputs = build_prompt(tokenizer, history)

		print("Assistant> ", end="", flush=True)
		answer = stream_generate(model, tokenizer, inputs, args)
		history.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
	main()
