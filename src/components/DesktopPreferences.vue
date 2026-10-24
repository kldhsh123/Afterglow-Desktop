<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Monitor, BellRing, LogOut, CircleHelp } from 'lucide-vue-next'
import ToggleRow from './ToggleRow.vue'
import { t } from '../i18n'
import { isDesktop } from '../services/desktop'
import { desktopPreferences, loadDesktopPreferences, saveDesktopPreferences, type CloseAction } from '../services/lifecycle'

const emit = defineEmits<{ error: [message: string] }>()
const saving = ref(false)
const options = [
  { value: 'ask' as CloseAction, key: 'desktop.ask' as const, hint: 'desktop.ask_hint' as const, icon: CircleHelp },
  { value: 'tray' as CloseAction, key: 'desktop.tray' as const, hint: 'desktop.tray_hint' as const, icon: BellRing },
  { value: 'exit' as CloseAction, key: 'desktop.exit' as const, hint: 'desktop.exit_hint' as const, icon: LogOut },
]
async function save(changes: Parameters<typeof saveDesktopPreferences>[0]) {
  if (saving.value) return
  saving.value = true
  try { await saveDesktopPreferences(changes) } catch (error) { emit('error', String(error)) }
  finally { saving.value = false }
}
onMounted(async () => { try { await loadDesktopPreferences() } catch (error) { emit('error', String(error)) } })
</script>

<template>
  <section class="desktop-preferences surface" :aria-label="t('desktop.title')">
    <div class="section-heading"><div><h2>{{ t('desktop.title') }}</h2><p>{{ t('desktop.scope') }}</p></div><Monitor :size="21"/></div>
    <fieldset><legend>{{ t('desktop.when_closing') }}</legend><div class="desktop-close-options">
      <button v-for="option in options" :key="option.value" type="button" role="radio" :aria-checked="desktopPreferences.closeAction === option.value" :disabled="saving || !isDesktop || (option.value === 'tray' && !desktopPreferences.trayAvailable)" :class="{ selected: desktopPreferences.closeAction === option.value }" @click="save({ closeAction: option.value })"><component :is="option.icon" :size="18"/><span><strong>{{ t(option.key) }}</strong><small>{{ t(option.hint) }}</small></span></button>
    </div></fieldset>
    <ToggleRow :model-value="desktopPreferences.autostart" :label="t('desktop.autostart')" :description="t('desktop.autostart_hint')" :disabled="saving || !isDesktop" @update:model-value="save({ autostart: $event })"/>
    <p class="muted">{{ t('desktop.saved_immediately') }}</p>
  </section>
</template>

<style scoped>
fieldset{border:0;padding:0;margin:0}legend{font-size:12px;margin-bottom:13px}.desktop-close-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.desktop-close-options>button{display:flex;align-items:flex-start;gap:10px;text-align:left;padding:16px 13px;border:1px solid var(--line);border-radius:10px;background:var(--surface)}.desktop-close-options>button:hover:not(:disabled){border-color:#b09a79}.desktop-close-options>button.selected{border-color:#a7865e;background:#f0e9d8}.desktop-close-options svg{margin-top:2px;color:var(--accent)}.desktop-close-options strong{display:block;font-size:12px;font-weight:500}.desktop-close-options small{display:block;font-size:10px;line-height:1.7;color:#78818c;margin-top:7px}.desktop-preferences .section-heading>svg{color:var(--accent)}@media(max-width:900px){.desktop-close-options{grid-template-columns:1fr}.desktop-close-options>button{padding:13px}.desktop-close-options small{margin-top:3px}}
</style>
