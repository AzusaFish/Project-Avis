"""
Module: scripts/import_persona_jsonl.py

Beginner note:
- This file is one building block of the backend system.
- Read class/function docstrings below to understand data flow.
"""

# 人格语料导入脚本：将 jsonl 文本写入 Chroma 向量库。

from __future__ import annotations

import argparse
import json
from pathlib import Path

from chromadb import PersistentClient


def main() -> None:
    # 读取 jsonl 人格语料并批量写入 Chroma collection。
    # 一行一个 JSON，对应一条可检索的人格语料。
    """Public API `main` used by other modules or route handlers."""
    parser = argparse.ArgumentParser(description="Import persona jsonl into Chroma")
    parser.add_argument("--input", required=True, help="Path to persona jsonl")
    parser.add_argument("--chroma-path", default="./data/chroma")
    parser.add_argument("--collection", default="persona_lines")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    client = PersistentClient(path=args.chroma_path)
    col = client.get_or_create_collection(args.collection)

    docs: list[str] = []
    ids: list[str] = []
    metadatas: list[dict] = []

    with input_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            text = obj.get("text", "").strip()
            if not text:
                continue
            docs.append(text)
            ids.append(f"{input_path.stem}-{idx}")
            metadatas.append(
                {
                    "speaker": obj.get("speaker", "unknown"),
                    "scene": obj.get("scene", ""),
                    "tags": ",".join(obj.get("tags", [])) if isinstance(obj.get("tags"), list) else "",
                    "emotion": obj.get("emotion", ""),
                }
            )

    if docs:
        # 批量 add 比逐条 add 性能更好。
        col.add(ids=ids, documents=docs, metadatas=metadatas)
    print(f"Imported {len(docs)} lines to {args.collection}")


if __name__ == "__main__":
    main()
