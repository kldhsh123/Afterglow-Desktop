<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { Minus, Square, Copy, X, BellRing } from 'lucide-vue-next'
import { isDesktop } from '../services/desktop'
import { t } from '../i18n'
import { desktopPreferences, loadDesktopPreferences, saveDesktopPreferences, applyCloseAction } from '../services/lifecycle'

const emit = defineEmits<{ error: [message: string] }>()
const maximized = ref(false)
const closeDialog = ref<HTMLDialogElement>()
const closing = ref(false)
const closeError = ref('')
const rememberClose = ref(false)
const listeners: (() => void)[] = []
let disposed = false
function trackListener(stop: () => void) { if (disposed) stop(); else listeners.push(stop) }
async function requestClose() {
  if (closing.value) return
  closeError.value = ''
  rememberClose.value = false
  try { await loadDesktopPreferences() } catch { /* Keep asking if preferences could not be read. */ }
  if (desktopPreferences.value.closeAction !== 'ask') {
    await chooseClose(desktopPreferences.value.closeAction)
    if (!closeError.value) return
  }
  if (!closeDialog.value?.open) {
    rememberClose.value = false
    closeDialog.value?.showModal()
  }
}
function cancelClose() { if (!closing.value) closeDialog.value?.close() }
async function chooseClose(action: 'tray' | 'exit') {
  if (closing.value) return
  closing.value = true
  closeError.value = ''
  try {
    if (rememberClose.value) await saveDesktopPreferences({ closeAction: action })
    await applyCloseAction(action)
    closeDialog.value?.close()
  } catch (error) { closeError.value = String(error) }
  finally { closing.value = false }
}
async function act(action: 'minimize' | 'toggleMaximize') {
  try { await getCurrentWindow()[action](); if (action === 'toggleMaximize') maximized.value = await getCurrentWindow().isMaximized() }
  catch (error) { emit('error', String(error)) }
}
onMounted(async () => {
  if (!isDesktop) return
  document.documentElement.classList.add('desktop-window')
  const window = getCurrentWindow()
  try {
    // Rust prevents native closing before the webview has loaded as well.
    trackListener(await window.listen('desktop-close-requested', () => { void requestClose() }))
    void loadDesktopPreferences().catch(() => {})
    maximized.value = await window.isMaximized()
    trackListener(await window.onResized(async () => { try { maximized.value = await window.isMaximized() } catch {} }))
  } catch (error) { emit('error', String(error)) }
})
onUnmounted(() => { disposed = true; listeners.forEach(stop => stop()); document.documentElement.classList.remove('desktop-window') })
</script>

<template>
  <header v-if="isDesktop" class="window-titlebar">
    <div class="window-drag-area" data-tauri-drag-region>
      <img src="/afterglow-icon.svg" alt=""/><span>Afterglow</span>
    </div>
    <div class="window-controls">
      <button type="button" :aria-label="t('window.minimize')" :title="t('window.minimize')" @click="act('minimize')"><Minus :size="14"/></button>
      <button type="button" :aria-label="t(maximized ? 'window.restore' : 'window.maximize')" :title="t(maximized ? 'window.restore' : 'window.maximize')" @click="act('toggleMaximize')"><Copy v-if="maximized" :size="12"/><Square v-else :size="12"/></button>
      <button type="button" class="window-close" :aria-label="t('window.close')" :title="t('window.close')" @click="requestClose"><X :size="16"/></button>
    </div>
  </header>
  <dialog v-if="isDesktop" ref="closeDialog" class="window-close-dialog" aria-labelledby="window-close-title" aria-describedby="window-close-description" :aria-busy="closing" @cancel.prevent="cancelClose" @click="event => { if (event.target === closeDialog) cancelClose() }">
    <div class="section-heading"><h2 id="window-close-title">{{ t('window.close_title') }}</h2><button type="button" class="icon-button" :disabled="closing" :aria-label="t('common.cancel')" @click="cancelClose"><X :size="18"/></button></div>
    <p id="window-close-description">{{ t('window.close_description') }}</p>
    <div class="window-close-choices">
      <button type="button" class="window-close-choice" autofocus :disabled="closing || !desktopPreferences.trayAvailable" @click="chooseClose('tray')"><BellRing :size="20"/><span><strong>{{ t('window.minimize_tray') }}</strong><small>{{ t('window.minimize_hint') }}</small></span></button>
      <button type="button" class="window-close-choice" :disabled="closing" @click="chooseClose('exit')"><X :size="20"/><span><strong>{{ t('window.exit') }}</strong><small>{{ t('window.exit_hint') }}</small></span></button>
    </div>
    <label class="remember-close"><input v-model="rememberClose" type="checkbox" :disabled="closing"/><span>{{ t('window.remember') }}<small>{{ t('window.remember_hint') }}</small></span></label>
    <p v-if="closeError" class="window-close-error" role="alert">{{ closeError }}</p>
    <div class="dialog-actions"><button type="button" class="button ghost" :disabled="closing" @click="cancelClose">{{ t('common.cancel') }}</button></div>
  </dialog>
</template>

<style scoped>
.window-close-dialog{width:min(460px,calc(100vw - 32px));max-height:calc(100dvh - 48px);overflow:auto;margin:auto;padding:26px;border:1px solid var(--line);border-radius:12px;background:var(--surface);color:var(--ink);box-shadow:0 22px 80px #1a2f4b30}
.window-close-dialog::backdrop{background:#1a2f4b60}
.window-close-dialog .section-heading{margin-bottom:10px}
.window-close-dialog>p{font-size:12px;color:#78818c}
.window-close-choices{display:grid;gap:10px;margin:22px 0 12px}
.window-close-choice{display:flex;align-items:center;gap:15px;width:100%;padding:17px 18px;text-align:left;color:var(--ink);background:var(--paper);border:1px solid #d9d6c7;border-radius:8px}
.window-close-choice:hover:not(:disabled){background:#ede8da;border-color:#b09a79}
.window-close-choice>svg{color:var(--accent)}
.window-close-choice span{min-width:0}
.window-close-choice strong{display:block;font-size:13px;font-weight:500}
.window-close-choice small{display:block;margin-top:6px;color:#78818c;font-size:11px;white-space:normal}
.window-close-dialog .window-close-error{color:#a44335;overflow-wrap:anywhere}
.remember-close{display:flex;align-items:flex-start;gap:10px;padding:9px 0;font-size:12px}.remember-close input{width:15px!important;height:15px;margin:2px 0 0;accent-color:var(--accent)}.remember-close small{display:block;margin-top:5px;color:#78818c;font-size:10px}
</style>
