# Live2D Desktop Frontend (Vue3 + Tauri)

该前端已默认对接 Core：

- WS: `ws://127.0.0.1:8080/ws/live2d`
- HTTP: `http://127.0.0.1:8080`

## Run

```powershell
npm install
npm run tauri dev
```

仅启动网页层：

```powershell
npm run dev
```

## Build

```powershell
npm run build
```

## Notes

- 如果你修改了 Core 端口，请在设置面板中同步修改 WS 与 HTTP 地址。
- 麦克风实时上传走 `ws://<core>/ws/audio`，文本聊天走 `/playground/text`。
- AI 播报音频默认从 `http://127.0.0.1:9880/v1/audio/speech` 拉取，可在设置面板修改 TTS 地址。
