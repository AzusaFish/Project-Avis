# Neuro English LLaMA-Factory Pipeline

This folder now includes a practical SFT + DPO workflow for your current setup:
- GPU: RTX 5070 Ti 16 GB
- Language: English only
- SFT core data: qlora_cleaned_manual.jsonl
- Vision retention data: sampled COCO subset from sharegpt4v_instruct_gpt4-vision_cap100k.json
- DPO parquet source: OpenHermespreferences-roleplay.parquet (truthy removed)
- Template strategy (recommended for InternVL): SFT uses `intern_vl`, DPO uses `intern_vl`.
- Vision retention should be prioritized: use a larger vision subset (for example `--vision-subset-size 4000`) and keep SFT vision mixing enabled.
- For faster expansion, you can increase concurrent downloads (for example `--vision-download-workers 24`).
- Optional text cleaning: local Ollama model

## 0) One Entry Only

This folder is simplified to a single training entry script:

```
start_everything.bat
```

It does all required steps in order:
- auto-create/reuse .conda-lf (Python 3.11)
- auto-install/update required packages
- run prepare_neuro_lf_data.py
- run SFT (train_neuro_sft_lora.yaml)
- run DPO (train_neuro_dpo_lora.yaml)

Useful options:

```
start_everything.bat
start_everything.bat --dry-run
start_everything.bat --no-pause
```

Generated files:
- datasets/neuro_sft_en.json
- datasets/neuro_vl_coco_subset.json
- datasets/neuro_uncensored_dpo_en.json
- datasets/qlora_bad_rows.json
- datasets/prepare_report.json
- datasets/dataset_info.json
- train_neuro_sft_lora.yaml
- train_neuro_dpo_lora.yaml

## 1) Outputs

- SFT adapter: outputs/neuro_sft_lora_internvl35_14b
- DPO adapter: outputs/neuro_dpo_lora_internvl35_14b

## Notes for your 16 GB VRAM card

- YAML defaults already use 4-bit quantization and conservative batch settings.
- If OOM happens:
  - reduce cutoff_len
  - increase gradient_accumulation_steps
  - reduce dataloader_num_workers
- Current defaults target InternVL3.5-14B with 16 GB-safe profile.

## Dependencies

- LLaMA-Factory installed in .conda-lf by setup_lf_env_5070ti.bat.
- pandas + pyarrow for parquet loading.
- Ollama optional for cleaning. If enabled, install at least one model first (for example: ollama pull qwen2.5:7b).

## Troubleshooting

- start_everything.bat writes rolling log: start_everything.last.log
- If errors appear, rerun with --no-pause disabled to keep message on screen.
