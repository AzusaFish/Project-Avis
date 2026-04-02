<script setup lang="ts">
// Live2D 画布组件：负责模型加载、渲染、拖拽和动作控制。
import { ref, onMounted, onUnmounted, watch, toRefs } from 'vue'
import * as PIXI from 'pixi.js'
import { Live2DModel } from 'pixi-live2d-display/cubism4'

const props = defineProps<{
  modelPath: string
  scale: number
  offsetX: number
  offsetY: number
}>()

const emit = defineEmits<{
  'update:offsetX': [value: number]
  'update:offsetY': [value: number]
}>()

const { modelPath, scale, offsetX, offsetY } = toRefs(props)

const canvasRef = ref<HTMLCanvasElement>()

function setCanvasRef(el: any) {
  // Vue 模板 ref 回调：拿到真实 canvas DOM。
  canvasRef.value = el as HTMLCanvasElement
}

let app: PIXI.Application | null = null
let model: InstanceType<typeof Live2DModel> | null = null
let expressionNames: string[] = []
let dragging = false
let dragStartX = 0
let dragStartY = 0
let dragStartOffsetX = 0
let dragStartOffsetY = 0

// Register Live2D interaction with PIXI ticker
;(window as any).PIXI = PIXI
Live2DModel.registerTicker(PIXI.Ticker)

async function loadModel(path: string) {
  // 核心加载逻辑：清理旧模型 -> 转换路径 -> 加载新模型。
  if (!app) return
  // Remove old model
  if (model) {
    app.stage.removeChild(model as any)
    model.destroy()
    model = null
    expressionNames = []
  }
  if (!path) return

  try {
    // Convert local path to Tauri asset URL with preserved slashes
    let url = path
    if (!url.startsWith('http')) {
      const normalized = path.replace(/\\/g, '/')
      url = 'http://asset.localhost/' + normalized.split('/').map(s => encodeURIComponent(s)).join('/')
    }

    model = await Live2DModel.from(url, { autoInteract: false })
    const settingExpr = (model as any)?.internalModel?.settings?.expressions
    if (Array.isArray(settingExpr)) {
      expressionNames = settingExpr
        .map((x: any) => String(x?.Name || x?.name || x?.File || x?.file || '').trim())
        .filter(Boolean)
    }
    model.scale.set(scale.value)
    model.x = (app.screen.width / 2) + offsetX.value
    model.y = (app.screen.height / 2) + offsetY.value
    model.anchor.set(0.5, 0.5)
    app.stage.addChild(model as any)
  } catch (e) {
    console.error('Failed to load Live2D model:', e)
  }
}

function updateTransform() {
  // 响应缩放和偏移滑块的变化。
  if (!model || !app) return
  model.scale.set(scale.value)
  model.x = (app.screen.width / 2) + offsetX.value
  model.y = (app.screen.height / 2) + offsetY.value
}

watch(modelPath, (val) => loadModel(val))
watch([scale, offsetX, offsetY], updateTransform)

onMounted(() => {
  // 初始化 PIXI 渲染器并绑定拖拽事件。
  if (!canvasRef.value) return
  const container = canvasRef.value.parentElement || canvasRef.value

  app = new PIXI.Application({
    view: canvasRef.value,
    backgroundColor: 0x000000,
    backgroundAlpha: 0,
    resizeTo: container,
    antialias: false,
    autoDensity: false,
    resolution: 1,
    forceCanvas: true,
  })

  // Limit frame rate to reduce CPU load
  app.ticker.maxFPS = 30

  // Model dragging
  canvasRef.value.addEventListener('mousedown', (e: MouseEvent) => {
    if (!model) return
    dragging = true
    dragStartX = e.clientX
    dragStartY = e.clientY
    dragStartOffsetX = offsetX.value
    dragStartOffsetY = offsetY.value
    canvasRef.value!.style.cursor = 'grabbing'
  })
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)

  if (modelPath.value) {
    loadModel(modelPath.value)
  }

  window.addEventListener('resize', () => {
    app?.resize()
    updateTransform()
  })
})

onUnmounted(() => {
  // 组件卸载时释放图形资源。
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
  model?.destroy()
  app?.destroy(true)
})

function onDragMove(e: MouseEvent) {
  // 拖拽时实时回传偏移值给父组件。
  if (!dragging) return
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  emit('update:offsetX', dragStartOffsetX + dx)
  emit('update:offsetY', dragStartOffsetY + dy)
}

function onDragEnd() {
  // 拖拽结束：复位状态并恢复鼠标样式。
  if (!dragging) return
  dragging = false
  if (canvasRef.value) canvasRef.value.style.cursor = 'grab'
}

function playMotion(group: string, index?: number) {
  // 播放 Live2D 动作（按 motion group 名称）。
  // 对外暴露的动作接口：由父组件根据后端指令调用。
  if (!model) return
  try {
    if (index !== undefined) {
      model.motion(group, index)
    } else {
      model.motion(group)
    }
  } catch (e) {
    console.warn(`[Live2D] motion "${group}" failed:`, e)
  }
}

function setExpression(nameOrIndex: string | number) {
  // 设置 Live2D 表情（支持名称或索引）。
  // 对外暴露的表情接口：支持表情名或索引。
  if (!model) return
  try {
    if (typeof nameOrIndex === 'number') {
      if (expressionNames.length > 0) {
        const idx = ((Math.floor(nameOrIndex) % expressionNames.length) + expressionNames.length) % expressionNames.length
        model.expression(idx)
      } else {
        model.expression(nameOrIndex)
      }
      return
    }

    const name = String(nameOrIndex || '').trim()
    if (!name) return
    const lower = name.toLowerCase()
    const matchedIndex = expressionNames.findIndex((x) => {
      const e = x.toLowerCase()
      return e === lower || e.includes(lower) || lower.includes(e)
    })
    if (matchedIndex >= 0) {
      model.expression(matchedIndex)
      return
    }
    model.expression(name)
  } catch (e) {
    console.warn(`[Live2D] expression "${nameOrIndex}" failed:`, e)
  }
}

function setMouthOpen(value: number) {
  // 通过 ParamMouthOpenY/ParamMouthForm 驱动口型，范围 [0, 1]。
  if (!model) return
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
  try {
    const core = (model as any)?.internalModel?.coreModel
    if (core && typeof core.setParameterValueById === 'function') {
      core.setParameterValueById('ParamMouthOpenY', v)
      core.setParameterValueById('ParamMouthForm', (v - 0.5) * 0.6)
    }
  } catch (e) {
    console.warn('[Live2D] set mouth param failed:', e)
  }
}

defineExpose({ playMotion, setExpression, setMouthOpen })
</script>

<template>
  <canvas :ref="setCanvasRef" class="live2d-canvas"></canvas>
</template>

<style scoped>
.live2d-canvas {
  display: block;
  width: 100%; height: 100%;
  cursor: grab;
}
</style>
