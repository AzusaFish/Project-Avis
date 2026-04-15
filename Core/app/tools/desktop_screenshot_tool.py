"""Desktop screenshot tool that only captures and returns image metadata."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from app.core.config import settings


class DesktopScreenshotTool:
    name = "desktop_screenshot"

    def _capture_windows(self, output_path: Path, max_edge: int) -> None:
        output = str(output_path).replace("'", "''")
        ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$g.Dispose()
if ($bmp.Width -gt {max_edge} -or $bmp.Height -gt {max_edge}) {{
  if ($bmp.Width -ge $bmp.Height) {{
    $newW = {max_edge}
    $newH = [int]($bmp.Height * {max_edge} / $bmp.Width)
  }} else {{
    $newH = {max_edge}
    $newW = [int]($bmp.Width * {max_edge} / $bmp.Height)
  }}
  $resized = New-Object System.Drawing.Bitmap $newW, $newH
  $g2 = [System.Drawing.Graphics]::FromImage($resized)
  $g2.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g2.DrawImage($bmp, 0, 0, $newW, $newH)
  $g2.Dispose()
  $bmp.Dispose()
  $bmp = $resized
}}
$bmp.Save('{output}', [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
""".strip()
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            check=True,
            capture_output=True,
            text=True,
        )

    async def call(self, args: dict) -> str:
        if os.name != "nt":
            return "desktop_screenshot failed: currently only supported on Windows host"

        question = str(args.get("question") or "Describe what is currently shown on the desktop.").strip()
        if not question:
            question = "Describe what is currently shown on the desktop."

        screenshot_dir = Path(__file__).resolve().parents[2] / "data" / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        screenshot_path = screenshot_dir / f"desktop_{ts}.png"

        try:
            self._capture_windows(screenshot_path, max(320, int(settings.screenshot_max_edge)))
        except Exception as exc:
            return f"desktop_screenshot failed: {exc}"

        result = {
            "screenshot_path": str(screenshot_path),
            "question": question,
        }
        return json.dumps(result, ensure_ascii=False)
