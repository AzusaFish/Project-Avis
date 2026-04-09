# Project Avis

Project Avis 是一款功能强大的多模态个人 AI 助手。本项目采用前后端分离架构，通过桌面级 Live2D 虚拟形象提供极具交互性的前端体验，并在后端集成了强大的 LLM 路由、长期记忆管理、语音交互、视觉理解以及多平台自动化接入。

此外，项目内置了完整的微调工作流（基于 LLaMA-Factory 和 Unsloth），支持针对特定 Persona 进行模型迭代与优化。

## 核心特性

- **多模态交互核心 (Core Agent)**
  - 基于上下文管理器 (Context Manager) 和规划器 (Planner) 的智能调度。
  - 内置长期记忆与反思机制 (Memory Reflector)，支持 ChromaDB 向量检索与 SQLite 本地存储。
  - 支持视觉服务和语音处理 (Realtime STT, Kokoro/Genie TTS)。
- **沉浸式桌面 UI (Live2D Desktop)**
  - 基于 Tauri + Vue3 + TypeScript 构建的轻量级跨平台桌面端。
  - 深度集成 Live2D Cubism 模型，支持多态表情与动作调度。
  - WebSockets 实时音频与状态流转。
- **开箱即用的模型微调框架 (Tuning)**
  - 集成 LLaMA-Factory 和 Unsloth 训练管道。
  - 提供数据清洗、SFT、DPO 流程的标准化 YAML 配置与一键导出脚本。

## 架构概览与目录结构

```text
Project-Avis/
├── Core/                   # Python 后端核心 (API, Agent, Services)
│   ├── app/                # 核心业务逻辑 (API 路由, 工具, 记忆, 视觉/语音服务)
│   ├── bridges/            # 跨平台桥接 (STT, TTS Http Bridges)
│   ├── configs/            # 核心配置文件目录
│   ├── datasets/           # 运行时使用的数据集/Persona
│   ├── wechat/             # 微信协议接入层
│   └── scripts/            # 后端启动与环境初始化脚本
├── live2d-desktop/         # Tauri + Vue 3 桌面端 (Live2D UI)
│   ├── src/                # Vue 3 前端代码 (Components, Canvas)
│   └── src-tauri/          # Tauri Rust 后端
├── Data/                   # 静态资源与训练原始数据
│   ├── Live2D Cubism/      # Live2D 模型文件 (Atri, Hiyori 等)
│   └── Training_Data/      # 数据清洗与构建资源
├── Tuning/                 # 模型微调与导出管道
│   ├── LLaMa_Factory/      # SFT/DPO 训练配置与启动脚本
│   └── Unsloth/            # 高效微调脚本与模型导出
└── scripts/                # 全局自动化脚本 (如环境检查、模型下载)
