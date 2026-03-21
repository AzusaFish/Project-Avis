<script setup lang="ts">
// 设置面板：编辑模型路径、位置缩放、以及 Core 通信地址。
const emit = defineEmits<{ close: []; 'refresh-audio-outputs': [] }>()

defineProps<{
  audioOutputDevices: Array<{ id: string; label: string }>
  sinkIdSupported: boolean
}>()

const modelPath = defineModel<string>('modelPath', { required: true })
const modelScale = defineModel<number>('modelScale', { required: true })
const modelX = defineModel<number>('modelX', { required: true })
const modelY = defineModel<number>('modelY', { required: true })
const wsUrl = defineModel<string>('wsUrl', { required: true })
const resServerUrl = defineModel<string>('resServerUrl', { required: true })
const ttsServerUrl = defineModel<string>('ttsServerUrl', { required: true })
const ttsVoiceOverride = defineModel<string>('ttsVoiceOverride', { required: true })
const ttsLangOverride = defineModel<string>('ttsLangOverride', { required: true })
const ttsVolume = defineModel<number>('ttsVolume', { required: true })
const audioOutputDeviceId = defineModel<string>('audioOutputDeviceId', { required: true })
</script>

<template>
  <div class="panel-backdrop" @click.self="emit('close')">
    <div class="panel" @click.stop>
      <div class="panel-header">
        <span>⚙ 设置</span>
        <button class="close-btn" @click="emit('close')">✕</button>
      </div>

      <div class="field">
        <label>Live2D 模型路径</label>
        <input v-model="modelPath" placeholder="D:/.../xxx.model3.json" />
        <small>model3.json 的完整路径</small>
      </div>

      <div class="field">
        <label>缩放 ({{ modelScale.toFixed(2) }})</label>
        <input type="range" v-model.number="modelScale" min="0.05" max="2" step="0.01" />
      </div>

      <div class="field-row">
        <div class="field">
          <label>X 偏移 ({{ modelX }})</label>
          <input type="range" v-model.number="modelX" min="-960" max="960" step="1" />
        </div>
        <div class="field">
          <label>Y 偏移 ({{ modelY }})</label>
          <input type="range" v-model.number="modelY" min="-960" max="960" step="1" />
        </div>
      </div>

      <div class="field">
        <label>WebSocket 地址</label>
        <input v-model="wsUrl" placeholder="ws://127.0.0.1:8080/ws/live2d" />
        <small>Core 的 Live2DProtocol 兼容 WS 地址</small>
      </div>

      <div class="field">
        <label>资源服务器地址</label>
        <input v-model="resServerUrl" placeholder="http://127.0.0.1:8080" />
        <small>Core HTTP 地址（/playground/text 与 /playground/microphone）</small>
      </div>

      <div class="field">
        <label>TTS 服务地址</label>
        <input v-model="ttsServerUrl" placeholder="http://127.0.0.1:9880" />
        <small>Kokoro /v1/audio/speech 地址（用于前端本地播报）</small>
      </div>

      <div class="field-row">
        <div class="field">
          <label>TTS 音色覆盖（可留空）</label>
          <input v-model="ttsVoiceOverride" placeholder="jf_alpha" />
        </div>
        <div class="field">
          <label>TTS 语言覆盖（可留空）</label>
          <input v-model="ttsLangOverride" placeholder="en-us" />
        </div>
      </div>
      <div class="field">
        <small>留空时使用 Kokoro 服务端默认（由 start_everything.bat / 环境变量控制）。</small>
      </div>

      <div class="field">
        <label>TTS 音量 ({{ Math.round(ttsVolume * 100) }}%)</label>
        <input type="range" v-model.number="ttsVolume" min="0" max="1" step="0.01" />
      </div>

      <div class="field">
        <label>音频输出设备</label>
        <template v-if="sinkIdSupported">
          <div class="inline-row">
            <select v-model="audioOutputDeviceId" class="select-box">
              <option value="">系统默认设备</option>
              <option v-for="d in audioOutputDevices" :key="d.id" :value="d.id">{{ d.label }}</option>
            </select>
            <button class="refresh-btn" @click="emit('refresh-audio-outputs')">刷新</button>
          </div>
          <small>选择用于 AI 语音播放的输出设备</small>
        </template>
        <template v-else>
          <small>当前运行环境不支持切换输出设备（setSinkId 不可用）</small>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel-backdrop {
  position: fixed; inset: 0;
  z-index: 10000;
  display: flex; align-items: center; justify-content: center;
  background: rgba(0,0,0,0.15);
}
.panel {
  background: rgba(30,30,30,0.92);
  backdrop-filter: blur(12px);
  border-radius: 14px;
  padding: 20px 24px;
  width: 380px; max-height: 80vh;
  overflow-y: auto;
  color: #e0e0e0;
  font-size: 13px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.panel-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px; font-size: 16px; font-weight: 600;
}
.close-btn {
  background: none; border: none; color: #aaa;
  font-size: 18px; cursor: pointer;
}
.close-btn:hover { color: #fff; }
.field { margin-bottom: 14px; }
.field label { display: block; margin-bottom: 4px; color: #bbb; font-size: 12px; }
.field input[type="text"], .field input:not([type]) {
  width: 100%; padding: 6px 10px;
  background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15);
  border-radius: 6px; color: #fff; font-size: 13px; outline: none;
}
.field input[type="text"]:focus, .field input:not([type]):focus {
  border-color: rgba(59,130,246,0.6);
}
.field input[type="range"] {
  width: 100%; accent-color: #3b82f6;
}
.field small { color: #777; font-size: 11px; }
.field-row { display: flex; gap: 12px; }
.field-row .field { flex: 1; }
.inline-row { display: flex; gap: 8px; }
.select-box {
  flex: 1;
  min-width: 0;
  background: rgba(255,255,255,0.08);
  border: 1px solid rgba(255,255,255,0.15);
  border-radius: 6px;
  color: #fff;
  padding: 6px 8px;
}
.refresh-btn {
  border: none;
  border-radius: 6px;
  padding: 6px 10px;
  background: rgba(59,130,246,0.8);
  color: #fff;
  cursor: pointer;
}
.refresh-btn:hover { background: rgba(59,130,246,1); }
</style>
