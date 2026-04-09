import argparse
import os
import re
import types
import wave
from pathlib import Path
from typing import Any

import numpy as np
import requests
import torch
import torchaudio
import yt_dlp
from pyannote.audio import Pipeline

# 默认配置
DEFAULT_VIDEO_URL = "https://www.youtube.com/watch?v=j8lF9-nNsyM"
DEFAULT_AUDIO_FILE = "neuro_vedal_audio.wav"
DEFAULT_PIPELINE_ID = "pyannote/speaker-diarization-3.1"
DEFAULT_SUBTITLE_LANGS = ("en", "en-US", "en-GB")

# 声学标签可按实际效果对调
SPEAKER_MAP = {
    "SPEAKER_00": "Vedal",
    "SPEAKER_01": "Neuro",
    "SPEAKER_UNKNOWN": "Unknown",
}


def _resolve_hf_token(cli_token: str | None) -> str:
    token = cli_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    token = (token or "").strip()
    if not token:
        raise RuntimeError(
            "缺少 HuggingFace Token。请传 --hf-token 或设置环境变量 HF_TOKEN。"
        )
    return token


def _video_id_from_url(url: str) -> str:
    if "v=" in url:
        return url.split("v=", 1)[1].split("&", 1)[0]
    return re.sub(r"\W+", "_", url)[-32:]


def _pick_subtitle_url(info: dict[str, Any]) -> str:
    subtitles = info.get("subtitles") or {}
    auto_caps = info.get("automatic_captions") or {}

    candidates = []
    for lang in DEFAULT_SUBTITLE_LANGS:
        candidates.extend(subtitles.get(lang, []))
    for lang in DEFAULT_SUBTITLE_LANGS:
        candidates.extend(auto_caps.get(lang, []))

    if not candidates:
        raise ValueError("未找到英文字幕流（subtitles/automatic_captions）。")

    json3 = next((s.get("url") for s in candidates if s.get("ext") == "json3" and s.get("url")), None)
    if json3:
        return json3

    first = next((s.get("url") for s in candidates if s.get("url")), None)
    if not first:
        raise ValueError("字幕流存在但没有可用 URL。")
    return first


def _clean_caption_text(text: str) -> str:
    text = text.replace("\n", " ").strip()
    if not text:
        return ""
    if text.startswith("[") and text.endswith("]"):
        return ""
    return " ".join(text.split())


def get_transcript_and_audio(url: str, audio_path: Path, keep_audio: bool) -> list[dict[str, Any]]:
    """阶段一：下载音频并提取带时间戳字幕事件。"""
    print("[*] 正在解析视频并下载音频...")
    script_dir = audio_path.parent.resolve()
    ffmpeg_exe = script_dir / "ffmpeg.exe"
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav"}],
        "outtmpl": str(audio_path.with_suffix("")),
        "quiet": True,
        "skip_download": False,
    }
    if ffmpeg_exe.exists():
        ydl_opts["ffmpeg_location"] = str(script_dir)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if not audio_path.exists():
        raise FileNotFoundError(f"音频文件未生成: {audio_path}")

    print(f"[+] 音频就绪: {audio_path}")
    subtitle_url = _pick_subtitle_url(info)
    print("[*] 正在下载 JSON3 字幕...")
    resp = requests.get(subtitle_url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()

    events: list[dict[str, Any]] = []
    for event in payload.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue

        text = "".join(seg.get("utf8", "") for seg in segs)
        text = _clean_caption_text(text)
        if not text:
            continue

        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        end = start + max(duration, 0.0)
        if end <= start:
            continue

        events.append({"text": text, "start": start, "end": end})

    if not events:
        raise RuntimeError("字幕事件为空，无法对齐说话人。")

    print(f"[+] 成功提取 {len(events)} 条字幕事件。")
    if keep_audio:
        print("[*] keep-audio 已启用，保留临时音频文件。")
    return events


def apply_windows_torchcodec_patch() -> None:
    """Windows 下旁路 torchcodec 失败路径，避免 AudioDecoder NameError。"""
    import pyannote.audio.core.io as io_mod

    if getattr(io_mod, "_NEURO_WINDOWS_PATCHED", False):
        return

    original_get_audio_metadata = io_mod.get_audio_metadata

    def _meta_from_waveform(waveform: torch.Tensor, sample_rate: int) -> types.SimpleNamespace:
        num_frames = int(waveform.shape[-1])
        sr = int(sample_rate)
        duration = (num_frames / sr) if sr > 0 else 0.0
        num_channels = int(waveform.shape[0]) if waveform.ndim > 1 else 1
        return types.SimpleNamespace(
            num_frames=num_frames,
            sample_rate=sr,
            num_channels=num_channels,
            duration_seconds_from_header=duration,
        )

    def _meta_from_path(path_like: Any) -> types.SimpleNamespace:
        with wave.open(str(path_like), "rb") as wf:
            sr = int(wf.getframerate())
            num_frames = int(wf.getnframes())
            num_channels = int(wf.getnchannels())
        duration = (num_frames / sr) if sr > 0 else 0.0
        return types.SimpleNamespace(
            num_frames=num_frames,
            sample_rate=sr,
            num_channels=num_channels,
            duration_seconds_from_header=duration,
        )

    def patched_get_audio_metadata(file: Any):
        # 明确支持 in-memory 音频输入
        if isinstance(file, dict) and "waveform" in file and "sample_rate" in file:
            return _meta_from_waveform(file["waveform"], int(file["sample_rate"]))

        try:
            return original_get_audio_metadata(file)
        except Exception:
            # fallback: 直接用 torchaudio 读取头信息
            if isinstance(file, dict):
                audio = file.get("audio")
                if audio is None:
                    raise
                return _meta_from_path(audio)
            return _meta_from_path(file)

    original_get_duration = io_mod.Audio.get_duration

    def patched_get_duration(self, file):
        try:
            return original_get_duration(self, file)
        except Exception:
            validated = self.validate_file(file)
            if "waveform" in validated:
                frames = int(validated["waveform"].shape[-1])
                sr = int(validated["sample_rate"])
                return frames / sr
            metadata = patched_get_audio_metadata(validated)
            return float(metadata.duration_seconds_from_header)

    io_mod.get_audio_metadata = patched_get_audio_metadata
    io_mod.Audio.get_duration = patched_get_duration
    io_mod._NEURO_WINDOWS_PATCHED = True
    print("[+] 已启用 Windows torchcodec 旁路补丁。")


def load_waveform_robust(audio_path: Path) -> tuple[torch.Tensor, int]:
    """优先尝试 torchaudio，失败时回退到 wave+numpy，彻底绕过 torchcodec。"""
    try:
        return torchaudio.load(str(audio_path))
    except Exception as exc:
        print(f"[WARN] torchaudio.load 失败，切换 wave 读取: {exc}")

    with wave.open(str(audio_path), "rb") as wf:
        sr = int(wf.getframerate())
        channels = int(wf.getnchannels())
        sample_width = int(wf.getsampwidth())
        frames = int(wf.getnframes())
        raw = wf.readframes(frames)

    if sample_width == 1:
        arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        arr = (arr - 128.0) / 128.0
    elif sample_width == 2:
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise RuntimeError(f"不支持的 WAV 采样宽度: {sample_width} 字节")

    if channels > 1:
        arr = arr.reshape(-1, channels).T
    else:
        arr = arr.reshape(1, -1)

    waveform = torch.from_numpy(arr)
    return waveform, sr


def run_acoustic_diarization(
    audio_path: Path,
    hf_token: str,
    num_speakers: int,
    max_audio_seconds: float,
) -> tuple[Any, float]:
    """阶段二：运行 pyannote 声纹切分（物理层）。"""
    os.environ["HF_TOKEN"] = hf_token
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    apply_windows_torchcodec_patch()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"[*] 推理设备: {device}")

    print(f"[*] 读取波形: {audio_path}")
    waveform, sample_rate = load_waveform_robust(audio_path)
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    if max_audio_seconds > 0:
        max_frames = int(max_audio_seconds * sample_rate)
        waveform = waveform[:, :max_frames]
        print(f"[*] quick-test: 仅使用前 {max_audio_seconds:.1f} 秒音频。")

    duration = float(waveform.shape[-1]) / float(sample_rate)
    print(f"[*] 实际送入 diarization 的时长: {duration:.2f} 秒")

    print("[*] 加载 pyannote 管道...")
    try:
        # pyannote >= 4.0
        pipeline = Pipeline.from_pretrained(DEFAULT_PIPELINE_ID, token=hf_token)
    except TypeError:
        # pyannote 3.x
        pipeline = Pipeline.from_pretrained(DEFAULT_PIPELINE_ID, use_auth_token=hf_token)
    pipeline.to(device)

    print("[*] 开始声纹切分...")
    diarization = pipeline(
        {
            "waveform": waveform,
            "sample_rate": sample_rate,
        },
        num_speakers=num_speakers,
    )
    print("[+] 声纹切分完成。")
    return diarization, duration


def _dominant_speaker_for_event(event: dict[str, Any], turns: list[tuple[float, float, str]]) -> str:
    start = event["start"]
    end = event["end"]
    best_label = "SPEAKER_UNKNOWN"
    best_overlap = 0.0
    for s, e, label in turns:
        if e <= start:
            continue
        if s >= end:
            break
        overlap = min(end, e) - max(start, s)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label
    return best_label


def align_and_merge(
    events: list[dict[str, Any]],
    diarization: Any,
    max_timeline_seconds: float,
    max_events: int,
) -> list[str]:
    """阶段三：字幕时间轴与声学切分结果对齐。"""
    print("[*] 正在融合声学边界与字幕时间戳...")

    if hasattr(diarization, "itertracks"):
        annotation = diarization
    elif hasattr(diarization, "speaker_diarization"):
        annotation = diarization.speaker_diarization
    elif hasattr(diarization, "annotation"):
        annotation = diarization.annotation
    else:
        raise TypeError(f"不支持的 diarization 输出类型: {type(diarization)}")

    turns = sorted(
        [(float(seg.start), float(seg.end), str(label)) for seg, _, label in annotation.itertracks(yield_label=True)],
        key=lambda x: x[0],
    )

    filtered = []
    for ev in events:
        if max_timeline_seconds > 0 and ev["start"] > max_timeline_seconds:
            break
        filtered.append(ev)
        if max_events > 0 and len(filtered) >= max_events:
            break

    raw_dialogue: list[tuple[str, str]] = []
    for ev in filtered:
        label = _dominant_speaker_for_event(ev, turns)
        speaker = SPEAKER_MAP.get(label, label)
        raw_dialogue.append((speaker, ev["text"]))

    print("[*] 合并连续同说话人段落...")
    merged: list[str] = []
    current_speaker = None
    buffer: list[str] = []

    for speaker, text in raw_dialogue:
        if speaker == current_speaker:
            buffer.append(text)
        else:
            if current_speaker is not None:
                merged.append(f"{current_speaker}: {' '.join(buffer)}")
            current_speaker = speaker
            buffer = [text]

    if current_speaker is not None:
        merged.append(f"{current_speaker}: {' '.join(buffer)}")

    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YouTube Neuro/Vedal 物理层说话人分离")
    parser.add_argument("--video-url", default=DEFAULT_VIDEO_URL)
    parser.add_argument("--audio-file", default=DEFAULT_AUDIO_FILE)
    parser.add_argument("--hf-token", default="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")
    parser.add_argument("--num-speakers", type=int, default=2)
    parser.add_argument("--max-audio-seconds", type=float, default=0.0)
    parser.add_argument("--max-events", type=int, default=0)
    parser.add_argument("--keep-audio", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    hf_token = _resolve_hf_token(args.hf_token.strip() or None)

    script_dir = Path(__file__).resolve().parent
    audio_path = (script_dir / args.audio_file).resolve()

    try:
        events = get_transcript_and_audio(args.video_url, audio_path, keep_audio=args.keep_audio)
        diarization, used_seconds = run_acoustic_diarization(
            audio_path=audio_path,
            hf_token=hf_token,
            num_speakers=max(1, args.num_speakers),
            max_audio_seconds=max(0.0, args.max_audio_seconds),
        )

        final_dialogue = align_and_merge(
            events=events,
            diarization=diarization,
            max_timeline_seconds=max(0.0, args.max_audio_seconds) if args.max_audio_seconds > 0 else used_seconds,
            max_events=max(0, args.max_events),
        )

        video_id = _video_id_from_url(args.video_url)
        output_file = script_dir / f"perfect_diarization_{video_id}.txt"
        output_file.write_text("\n".join(final_dialogue), encoding="utf-8")

        print("\n" + "=" * 50)
        print("✅ 物理层切分完毕！结果预览：\n")
        print("\n".join(final_dialogue[:10]))
        print("...\n" + "=" * 50)
        print(f"✅ 完整结果已保存至: {output_file}")
    finally:
        if (not args.keep_audio) and audio_path.exists():
            audio_path.unlink()
            print("[*] 已清理临时音频文件。")


if __name__ == "__main__":
    main()