# WeChat Integration (Paused)

This folder centralizes all WeChat access/integration code.

## Structure
- `bridge/`: WeChat bridge service implementation
- `runtime/`: Core runtime adapters (`wechat_guard`, `wechat_tool`)
- `scripts/`: diagnostics/bootstrap/security helper scripts
- `launchers/`: dedicated launcher bat files

## Current status
- WeChat integration is intentionally paused.
- Project default is `WECHAT_BRIDGE_PROVIDER: local` in `config.yaml`.

## Safe alternatives (recommended)
- Telegram Bot API
- Discord Bot API
- Matrix (self-hosted bridge)
- Email/SMTP polling bridge
- Web dashboard chat channel
