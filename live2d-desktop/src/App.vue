<script setup lang="ts">
// 顶层页面：负责把 Live2D 画布、字幕、设置面板和通信逻辑组装在一起。
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import Live2DCanvas from './components/Live2DCanvas.vue'
import SubtitleOverlay from './components/SubtitleOverlay.vue'
import SettingsPanel from './components/SettingsPanel.vue'

const appWindow = getCurrentWindow()

// ===== 页面配置状态（会持久化到 localStorage） =====
const showSettings = ref(false)
const modelPath = ref(localStorage.getItem('l2d_modelPath') || 'D:/AzusaFish/Codes/Development/Project-Avis/Data/Live2D Cubism/hiyori_free_zh/hiyori_free_zh/runtime/hiyori_free_t08.model3.json')
const modelScale = ref(Number(localStorage.getItem('l2d_modelScale')) || 0.25)
const modelX = ref(Number(localStorage.getItem('l2d_modelX')) || 0)
const modelY = ref(Number(localStorage.getItem('l2d_modelY')) || 0)
const wsUrl = ref(localStorage.getItem('l2d_wsUrl') || 'ws://127.0.0.1:8080/ws/live2d')
const resServerUrl = ref(localStorage.getItem('l2d_resServerUrl') || 'http://127.0.0.1:8080')
const ttsServerUrl = ref(localStorage.getItem('l2d_ttsServerUrl') || 'http://127.0.0.1:9880')
const ttsVolume = ref(Number(localStorage.getItem('l2d_ttsVolume')) || 0.9)
const audioOutputDeviceId = ref(localStorage.getItem('l2d_audioOutputDeviceId') || '')
const audioOutputDevices = ref<MediaDeviceInfo[]>([])
const sinkIdSupported = typeof (HTMLMediaElement.prototype as any).setSinkId === 'function'

// ===== 字幕与聊天状态 =====
const userText = ref('')
const botText = ref('')
const chatInput = ref('')
const isSending = ref(false)
const showChatInput = ref(false)
const live2dRef = ref<InstanceType<typeof Live2DCanvas>>()

// ===== 麦克风录音 + VAD =====
const micEnabled = ref(false)
const micSpeaking = ref(false) // 是否正在说话（用于 UI 指示）

const MIC_SAMPLE_RATE = 16000
const SILENCE_THRESHOLD = 0.008 // RMS 能量阈值（调低，避免普通麦克风过不了门限）
const SILENCE_DURATION = 600    // 静默超时
const MIC_STREAM_INTERVAL_MS = 120

let micStream: MediaStream | null = null
let micAudioCtx: AudioContext | null = null
let micProcessor: ScriptProcessorNode | null = null
let micSource: MediaStreamAudioSourceNode | null = null
let hasSpeech = false
let silenceTimer: ReturnType<typeof setTimeout> | null = null
let interruptSent = false
let micFrameSeq = 0
let lastMicSendTs = 0

let audioWs: WebSocket | null = null
let ttsQueue: string[] = []
let ttsPlaying = false
let currentTtsAudio: HTMLAudioElement | null = null
let lastTtsObjectUrl: string | null = null
let audioUnlockBound = false
let assistantStreamPrevText = ''
let ttsPendingStreamText = ''

const STREAM_TTS_CHUNK_CHARS = 90
const STREAM_TTS_MIN_CHARS = 10

function normalizeAudioOutputName(device: MediaDeviceInfo): string {
  return device.label?.trim() || `Audio Output ${device.deviceId.slice(0, 6)}`
}

async function refreshAudioOutputDevices() {
  try {
    const all = await navigator.mediaDevices.enumerateDevices()
    audioOutputDevices.value = all.filter((d) => d.kind === 'audiooutput')
    if (
      audioOutputDeviceId.value
      && !audioOutputDevices.value.some((d) => d.deviceId === audioOutputDeviceId.value)
    ) {
      audioOutputDeviceId.value = ''
    }
  } catch (e) {
    console.warn('[Audio] enumerate output devices failed:', e)
    audioOutputDevices.value = []
    audioOutputDeviceId.value = ''
  }
}

function splitSpeakableChunks(delta: string, forceFlush = false): string[] {
  if (delta) ttsPendingStreamText += delta
  const chunks: string[] = []

  while (true) {
    const text = ttsPendingStreamText
    if (!text) break

    const punctIndex = text.search(/[。！？!?；;,.，]/)
    if (punctIndex >= STREAM_TTS_MIN_CHARS) {
      const chunk = text.slice(0, punctIndex + 1).trim()
      ttsPendingStreamText = text.slice(punctIndex + 1).trimStart()
      if (chunk) chunks.push(chunk)
      continue
    }

    if (text.length >= STREAM_TTS_CHUNK_CHARS) {
      const windowText = text.slice(0, STREAM_TTS_CHUNK_CHARS)
      const splitAt = Math.max(windowText.lastIndexOf(' '), windowText.lastIndexOf('，'), windowText.lastIndexOf(','))
      const cut = splitAt > STREAM_TTS_MIN_CHARS ? splitAt : STREAM_TTS_CHUNK_CHARS
      const chunk = text.slice(0, cut).trim()
      ttsPendingStreamText = text.slice(cut).trimStart()
      if (chunk) chunks.push(chunk)
      continue
    }

    break
  }

  if (forceFlush && ttsPendingStreamText.trim()) {
    chunks.push(ttsPendingStreamText.trim())
    ttsPendingStreamText = ''
  }
  return chunks
}

function stopTtsPlayback() {
  if (currentTtsAudio) {
    currentTtsAudio.pause()
    currentTtsAudio.currentTime = 0
  }
  if (lastTtsObjectUrl) {
    URL.revokeObjectURL(lastTtsObjectUrl)
    lastTtsObjectUrl = null
  }
  currentTtsAudio = null
  ttsQueue = []
  ttsPendingStreamText = ''
  assistantStreamPrevText = ''
  ttsPlaying = false
}

function bindAudioUnlock() {
  if (audioUnlockBound) return
  audioUnlockBound = true
  const unlock = () => {
    const a = new Audio()
    // iOS / Chromium autoplay policy: establish user-gesture playback capability once.
    a.muted = true
    a.play().catch(() => undefined).finally(() => {
      a.pause()
      window.removeEventListener('pointerdown', unlock)
      window.removeEventListener('keydown', unlock)
    })
  }
  window.addEventListener('pointerdown', unlock, { once: true })
  window.addEventListener('keydown', unlock, { once: true })
}

async function playAssistantTts(text: string) {
  const cleaned = text.trim()
  if (!cleaned) return
  ttsQueue.push(cleaned)
  if (ttsPlaying) return
  ttsPlaying = true

  try {
    while (ttsQueue.length > 0) {
      const next = ttsQueue.shift()!
      const resp = await fetch(`${ttsServerUrl.value.replace(/\/$/, '')}/v1/audio/speech`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: 'kokoro',
          input: next,
          voice: 'af_sky',
          lang: 'en-us',
          response_format: 'wav',
          speed: 1.0,
        }),
      })
      if (!resp.ok) {
        console.error('[TTS] synth failed:', resp.status, await resp.text().catch(() => ''))
        continue
      }

      const audioBlob = await resp.blob()
      const objectUrl = URL.createObjectURL(audioBlob)
      const audio = new Audio(objectUrl)
      audio.volume = Math.max(0, Math.min(1, ttsVolume.value))
      if (sinkIdSupported && audioOutputDeviceId.value) {
        try {
          await (audio as any).setSinkId(audioOutputDeviceId.value)
        } catch (e) {
          console.warn('[Audio] setSinkId failed:', e)
        }
      }
      currentTtsAudio = audio
      lastTtsObjectUrl = objectUrl
      try {
        await audio.play()
      } catch (e) {
        console.error('[TTS] autoplay blocked or playback failed:', e)
        break
      }

      await new Promise<void>((resolve) => {
        const done = () => {
          audio.removeEventListener('ended', done)
          audio.removeEventListener('error', done)
          URL.revokeObjectURL(objectUrl)
          if (lastTtsObjectUrl === objectUrl) lastTtsObjectUrl = null
          if (currentTtsAudio === audio) currentTtsAudio = null
          resolve()
        }
        audio.addEventListener('ended', done)
        audio.addEventListener('error', done)
      })
    }
  } finally {
    ttsPlaying = false
  }
}

// 把 http:// 或 https:// 地址转换成 ws:// / wss://，用于音频实时上传。
function toWsBase(httpUrl: string): string {
  if (httpUrl.startsWith('https://')) return `wss://${httpUrl.slice('https://'.length)}`
  if (httpUrl.startsWith('http://')) return `ws://${httpUrl.slice('http://'.length)}`
  return httpUrl
}

function getAudioWsUrl() {
  // 音频专用 WS 路径固定为 /ws/audio
  return `${toWsBase(resServerUrl.value).replace(/\/$/, '')}/ws/audio`
}

function connectAudioWs() {
  // 建立音频上传通道，失败时在麦克风开启状态下自动重连。
  // 已连接/连接中时不重复创建。
  if (audioWs && (audioWs.readyState === WebSocket.OPEN || audioWs.readyState === WebSocket.CONNECTING)) return
  try {
    audioWs = new WebSocket(getAudioWsUrl())
    audioWs.onopen = () => console.log('[AudioWS] connected')
    audioWs.onclose = () => {
      if (micEnabled.value) setTimeout(connectAudioWs, 1500)
    }
    audioWs.onerror = () => audioWs?.close()
  } catch {
    if (micEnabled.value) setTimeout(connectAudioWs, 1500)
  }
}

function closeAudioWs() {
  // 释放音频 WS 连接句柄，避免重复连接或资源泄漏。
  // 主动关闭，避免切换地址或退出时残留连接。
  audioWs?.close()
  audioWs = null
}

function enqueueAssistantDeltaForTts(fullText: string) {
  if (!fullText) return
  let delta = ''
  if (fullText.startsWith(assistantStreamPrevText)) {
    delta = fullText.slice(assistantStreamPrevText.length)
  } else {
    delta = fullText
    ttsPendingStreamText = ''
  }
  assistantStreamPrevText = fullText

  const chunks = splitSpeakableChunks(delta)
  for (const c of chunks) {
    void playAssistantTts(c)
  }
}

function flushAssistantTts() {
  const chunks = splitSpeakableChunks('', true)
  for (const c of chunks) {
    void playAssistantTts(c)
  }
  assistantStreamPrevText = ''
}

function floatToPcm16Base64(samples: Float32Array): string {
  // 将 WebAudio 浮点采样压缩为 16-bit PCM 并编码为 Base64。
  // 浏览器音频是 Float32，这里转成后端常用 PCM16LE，再 base64 传输。
  const pcm = new Int16Array(samples.length)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  const bytes = new Uint8Array(pcm.buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

function sendMicChunk(samples: Float32Array) {
  // 发送一帧麦克风数据到后端音频 WS。
  // 限速发送：减少网络压力与后端排队。
  if (!audioWs || audioWs.readyState !== WebSocket.OPEN) return
  const now = Date.now()
  if (now - lastMicSendTs < MIC_STREAM_INTERVAL_MS) return
  lastMicSendTs = now
  const payload = {
    type: 'audio',
    sample_rate: MIC_SAMPLE_RATE,
    seq: micFrameSeq++,
    audio: floatToPcm16Base64(samples),
  }
  audioWs.send(JSON.stringify(payload))
}

async function startMic() {
  // 开启录音并启动 VAD（语音活动检测）逻辑。
  // 打开麦克风权限并创建 WebAudio 处理链。
  // 先检查是否存在可用音频输入设备；无设备时浏览器通常不会弹授权框。
  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    const hasMic = devices.some(d => d.kind === 'audioinput')
    if (!hasMic) {
      console.error('[Mic] no audioinput device found')
      alert('未检测到麦克风设备，无法启用语音输入。请插入麦克风后重试。')
      micEnabled.value = false
      return
    }
  } catch (e) {
    console.warn('[Mic] enumerateDevices failed:', e)
  }

  try {
    if (!window.isSecureContext) {
      alert('麦克风不可用：当前页面不是安全上下文（需 localhost/https）。')
      micEnabled.value = false
      return
    }
    if (navigator.permissions?.query) {
      const perm = await navigator.permissions.query({ name: 'microphone' as PermissionName })
      if (perm.state === 'denied') {
        alert('麦克风权限已被拒绝。请在系统或浏览器站点设置中将 localhost 的麦克风权限改为允许，然后重启前端。')
        micEnabled.value = false
        return
      }
    }

    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: MIC_SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    })
  } catch (e: any) {
    const errName = e?.name || 'UnknownError'
    const errMsg = e?.message || String(e)
    console.error('[Mic] getUserMedia failed:', errName, errMsg)
    if (errName === 'NotAllowedError') {
      alert(
        '麦克风权限被拒绝（NotAllowedError）。\n' +
        '请检查：\n' +
        '1) Windows 设置 -> 隐私和安全性 -> 麦克风 -> 允许桌面应用访问麦克风。\n' +
        '2) 若在浏览器调试，给 localhost:1420 站点开启麦克风权限。\n' +
        '3) 关闭后重开本程序再试。'
      )
    } else {
      alert(`麦克风不可用: ${errName}\n${errMsg}`)
    }
    micEnabled.value = false
    return
  }

  connectAudioWs()

  micAudioCtx = new AudioContext({ sampleRate: MIC_SAMPLE_RATE })
  micSource = micAudioCtx.createMediaStreamSource(micStream)
  micProcessor = micAudioCtx.createScriptProcessor(4096, 1, 1)

  micProcessor.onaudioprocess = (e) => {
    const data = e.inputBuffer.getChannelData(0)
    // 计算 RMS 能量
    let sum = 0
    for (let i = 0; i < data.length; i++) sum += data[i] * data[i]
    const rms = Math.sqrt(sum / data.length)

    if (rms > SILENCE_THRESHOLD) {
      // 检测到语音
      hasSpeech = true
      micSpeaking.value = true
      if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null }
      if (!interruptSent && audioWs?.readyState === WebSocket.OPEN) {
        // 首次检测到说话时发送 interrupt，优先打断当前播报。
        interruptSent = true
        stopTtsPlayback()
        audioWs.send(JSON.stringify({ type: 'interrupt' }))
      }
      sendMicChunk(new Float32Array(data))
    } else if (hasSpeech && !silenceTimer) {
      if (!silenceTimer) {
        silenceTimer = setTimeout(() => {
          micSpeaking.value = false
          hasSpeech = false
          interruptSent = false
          silenceTimer = null
        }, SILENCE_DURATION)
      }
    }
  }

  micSource.connect(micProcessor)
  micProcessor.connect(micAudioCtx.destination)
  console.log('[Mic] Recording started')
}

function stopMic() {
  // 关闭音频节点与设备句柄，防止麦克风占用。
  if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null }
  micProcessor?.disconnect()
  micSource?.disconnect()
  micProcessor = null
  micSource = null
  if (micAudioCtx) { micAudioCtx.close(); micAudioCtx = null }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null }
  closeAudioWs()
  hasSpeech = false
  interruptSent = false
  micSpeaking.value = false
  console.log('[Mic] Recording stopped')
}

function toggleMic() {
  micEnabled.value = !micEnabled.value
  if (micEnabled.value) { startMic() } else { stopMic() }
}
// ===== 麦克风录音结束 =====

// 动作名 → Live2D 表情索引映射（可根据模型实际表情调整）
const EXPRESSION_MAP: Record<string, number> = {
  '开心': 1,
  '难过': 2,
  '惊讶': 3,
  '生气': 4,
  '害羞': 5,
  '得意': 6,
  '普通': 0,
}
// 动作名 → Live2D motion group 映射
const MOTION_MAP: Record<string, string> = {
  '点头': 'TapHead',
  '摇头': 'Flick',
  '招手': 'TapBody',
}

function handleLive2dAction(actionName: string) {
  // 把后端动作名映射为具体表情或 motion。
  if (!live2dRef.value) return
  if (actionName in EXPRESSION_MAP) {
    live2dRef.value.setExpression(EXPRESSION_MAP[actionName])
  } else if (actionName in MOTION_MAP) {
    live2dRef.value.playMotion(MOTION_MAP[actionName])
  } else {
    // 尝试直接当表情名用
    live2dRef.value.setExpression(actionName)
  }
}

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let userClearTimer: ReturnType<typeof setTimeout> | null = null
let botClearTimer: ReturnType<typeof setTimeout> | null = null

function connectWs() {
  // 主业务 WS：接收字幕、动作、流式文本。
  if (ws && ws.readyState === WebSocket.OPEN) return
  try {
    ws = new WebSocket(wsUrl.value, 'Live2DProtocol')
    ws.onopen = () => {
      console.log('[WS] connected')
      ws!.send(JSON.stringify({
        protocol: 'Live2DProtocol', version: '1.1',
        message: '', action: 'client_hello', code: 0, data: null
      }))
    }
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.action === 'add_history' && msg.data) {
          const { role, text } = msg.data
          if (role === 'user') {
            userText.value = text || ''
            if (userClearTimer) clearTimeout(userClearTimer)
            userClearTimer = setTimeout(() => { userText.value = '' }, 8000)
          } else if (role === 'assistant') {
            botText.value = text || ''
            const hadStream = assistantStreamPrevText.length > 0 || ttsPendingStreamText.trim().length > 0
            flushAssistantTts()
            if (!hadStream && text) {
              void playAssistantTts(String(text))
            }
            if (botClearTimer) clearTimeout(botClearTimer)
            botClearTimer = setTimeout(() => { botText.value = '' }, 12000)
          }
        } else if (msg.action === 'show_user_text_input' && msg.data) {
          userText.value = msg.data.text || ''
          if (userClearTimer) clearTimeout(userClearTimer)
          userClearTimer = setTimeout(() => { userText.value = '' }, 8000)
        } else if (msg.action === 'assistant_stream' && msg.data) {
          const streamText = String(msg.data.text || '')
          botText.value = streamText
          enqueueAssistantDeltaForTts(streamText)
          if (botClearTimer) clearTimeout(botClearTimer)
          botClearTimer = setTimeout(() => { botText.value = '' }, 12000)
        } else if (msg.action === 'live2d_action' && msg.data) {
          const actionName = msg.data.action_name
          if (actionName) {
            console.log('[WS] Live2D action:', actionName)
            handleLive2dAction(actionName)
          }
        }
      } catch { /* ignore parse errors */ }
    }
    ws.onclose = () => scheduleReconnect()
    ws.onerror = () => { /* suppress */ ws?.close() }
  } catch {
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(connectWs, 5000)
}

watch([modelPath, modelScale, modelX, modelY, wsUrl, resServerUrl, ttsServerUrl, ttsVolume, audioOutputDeviceId], () => {
  // 实时保存设置，重启前端后自动恢复。
  localStorage.setItem('l2d_modelPath', modelPath.value)
  localStorage.setItem('l2d_modelScale', String(modelScale.value))
  localStorage.setItem('l2d_modelX', String(modelX.value))
  localStorage.setItem('l2d_modelY', String(modelY.value))
  localStorage.setItem('l2d_wsUrl', wsUrl.value)
  localStorage.setItem('l2d_resServerUrl', resServerUrl.value)
  localStorage.setItem('l2d_ttsServerUrl', ttsServerUrl.value)
  localStorage.setItem('l2d_ttsVolume', String(ttsVolume.value))
  localStorage.setItem('l2d_audioOutputDeviceId', audioOutputDeviceId.value)
})

watch(ttsVolume, () => {
  if (currentTtsAudio) currentTtsAudio.volume = Math.max(0, Math.min(1, ttsVolume.value))
})

watch(wsUrl, () => {
  // 切换 WS 地址后重连。
  ws?.close()
  connectWs()
})

watch(resServerUrl, () => {
  // 切换 Core 地址后重建音频上传连接。
  closeAudioWs()
  if (micEnabled.value) connectAudioWs()
})

onMounted(() => {
  bindAudioUnlock()
  void refreshAudioOutputDevices()
  navigator.mediaDevices?.addEventListener?.('devicechange', refreshAudioOutputDevices)
  connectWs()
})
onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  ws?.close()
  navigator.mediaDevices?.removeEventListener?.('devicechange', refreshAudioOutputDevices)
  stopMic()
  stopTtsPlayback()
})

function startDrag() {
  // 让窗口进入可拖动状态（Tauri 无边框窗口）。
  appWindow.startDragging()
}

async function sendChat() {
  // 发送文本输入到 Core 的兼容接口。
  // 文本输入走兼容接口 /playground/text
  const text = chatInput.value.trim()
  if (!text || isSending.value) return
  isSending.value = true
  try {
    const resp = await fetch(`${resServerUrl.value}/playground/text`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    })
    if (resp.ok) {
      chatInput.value = ''
    }
  } catch (e) {
    console.error('[Chat] send failed:', e)
  } finally {
    isSending.value = false
  }
}
</script>

<template>
  <div class="app-root">
    <div class="title-bar" @mousedown="startDrag">
      <span class="title-text">Project Avis Live2D</span>
      <div class="title-btns" @mousedown.stop>
        <button
          class="title-btn mic-btn"
          :class="{ 'mic-on': micEnabled, 'mic-speaking': micSpeaking }"
          @click="toggleMic"
          :title="micEnabled ? '关闭麦克风' : '打开麦克风'"
        >🎤</button>
        <button class="title-btn" @click="showChatInput = !showChatInput" title="聊天">💬</button>
        <button class="title-btn" @click="showSettings = !showSettings" title="设置">⚙</button>
        <button class="title-btn" @click="appWindow.minimize()" title="最小化">─</button>
        <button class="title-btn close-btn" @click="appWindow.close()" title="关闭">✕</button>
      </div>
    </div>
    <div class="canvas-area">
      <Live2DCanvas
        ref="live2dRef"
        :model-path="modelPath"
        :scale="modelScale"
        :offset-x="modelX"
        :offset-y="modelY"
        @update:offset-x="v => modelX = v"
        @update:offset-y="v => modelY = v"
      />
      <SubtitleOverlay :user-text="userText" :bot-text="botText" />
      <transition name="slide">
        <div v-if="showChatInput" class="chat-bar" @mousedown.stop>
          <input
            v-model="chatInput"
            class="chat-input"
            placeholder="输入消息..."
            @keydown.enter="sendChat"
            :disabled="isSending"
          />
          <button class="chat-send" @click="sendChat" :disabled="isSending || !chatInput.trim()">
            {{ isSending ? '...' : '发送' }}
          </button>
        </div>
      </transition>
    </div>
    <SettingsPanel
      v-if="showSettings"
      v-model:modelPath="modelPath"
      v-model:modelScale="modelScale"
      v-model:modelX="modelX"
      v-model:modelY="modelY"
      v-model:wsUrl="wsUrl"
      v-model:resServerUrl="resServerUrl"
      v-model:ttsServerUrl="ttsServerUrl"
      v-model:ttsVolume="ttsVolume"
      v-model:audioOutputDeviceId="audioOutputDeviceId"
      :audio-output-devices="audioOutputDevices.map((d) => ({ id: d.deviceId, label: normalizeAudioOutputName(d) }))"
      :sink-id-supported="sinkIdSupported"
      @refresh-audio-outputs="refreshAudioOutputDevices"
      @close="showSettings = false"
    />
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app, .app-root {
  width: 100%; height: 100%;
  overflow: hidden;
  background: transparent;
}
.app-root {
  display: flex;
  flex-direction: column;
}
.title-bar {
  height: 28px;
  background: rgba(22,33,62,0.6);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px;
  cursor: grab;
  user-select: none;
  flex-shrink: 0;
  border-radius: 8px 8px 0 0;
}
.title-text {
  color: #8892b0;
  font-size: 12px;
  font-weight: 500;
}
.title-btns {
  display: flex; gap: 2px;
}
.title-btn {
  width: 28px; height: 24px;
  background: none; border: none;
  color: #8892b0; font-size: 13px;
  cursor: pointer; border-radius: 4px;
  display: flex; align-items: center; justify-content: center;
}
.title-btn:hover { background: rgba(255,255,255,0.1); color: #ccd6f6; }
.close-btn:hover { background: #e74c3c; color: #fff; }
.mic-btn.mic-on {
  background: rgba(34,197,94,0.35);
  color: #4ade80;
}
.mic-btn.mic-speaking {
  background: rgba(34,197,94,0.6);
  color: #fff;
  animation: mic-pulse 0.8s ease-in-out infinite;
}
@keyframes mic-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.canvas-area {
  flex: 1;
  position: relative;
  overflow: hidden;
}
.chat-bar {
  position: absolute;
  bottom: 124px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 6px;
  z-index: 20000;
  width: 80%;
  max-width: 500px;
  color: white;
}
.chat-input {
  flex: 1;
  padding: 8px 14px;
  border: none;
  border-radius: 20px;
  background: rgba(255,255,255,0.15);
  backdrop-filter: blur(10px);
  color: #f0f0f0;
  font-size: 14px;
  outline: none;
}
.chat-input::placeholder {
  color: rgba(255,255,255,0.4);
}
.chat-input:focus {
  background: rgba(255,255,255,0.25);
}
.chat-send {
  padding: 8px 16px;
  border: none;
  border-radius: 20px;
  background: rgba(59,130,246,0.8);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.chat-send:hover:not(:disabled) {
  background: rgba(59,130,246,1);
}
.chat-send:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.slide-enter-active, .slide-leave-active {
  transition: all 0.25s ease;
}
.slide-enter-from, .slide-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(10px);
}
</style>
