<script setup lang="ts">
// 字幕层：显示用户和助手的两条气泡字幕。
defineProps<{
  userText: string
  botText: string
}>()
</script>

<template>
  <div class="subtitle-layer">
    <div class="subtitle-dock">
      <transition name="fade">
        <div v-if="userText" class="subtitle user-sub">
          <span class="sub-role">YOU</span>
          <span class="sub-text">{{ userText }}</span>
        </div>
      </transition>
      <transition name="fade">
        <div v-if="botText" class="subtitle bot-sub">
          <span class="sub-role">AI</span>
          <span class="sub-text">{{ botText }}</span>
        </div>
      </transition>
    </div>
  </div>
</template>

<style scoped>
.subtitle-layer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 12px;
  z-index: 21000;
  display: flex;
  justify-content: center;
  pointer-events: none;
}

.subtitle-dock {
  width: min(1100px, 94vw);
  padding: 10px 14px;
  border-radius: 14px;
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.2), rgba(0, 0, 0, 0.5));
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.subtitle {
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 16px;
  line-height: 1.5;
  max-width: 100%;
  word-break: break-word;
  text-align: left;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

.user-sub {
  background: rgba(56, 189, 248, 0.35);
  color: #fff;
}

.bot-sub {
  background: rgba(15, 23, 42, 0.72);
  color: #e8f4ff;
}

.sub-role {
  display: inline-block;
  width: 48px;
  color: rgba(255, 255, 255, 0.85);
  font-size: 11px;
  letter-spacing: 1px;
  margin-right: 8px;
  vertical-align: top;
}

.sub-text {
  display: inline;
}

.fade-enter-active, .fade-leave-active {
  transition: opacity 0.35s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
