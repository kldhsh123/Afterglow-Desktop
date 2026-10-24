<script setup lang="ts">
import { Bug, ExternalLink, RefreshCw } from 'lucide-vue-next'
import type { DebugPreferences } from '../domain/settings'
import { t } from '../i18n'
import { isDesktop } from '../services/desktop'
import ToggleRow from './ToggleRow.vue'
const props = defineProps<{ preferences: DebugPreferences; pendingApply: boolean; changed: boolean; running: boolean; available: boolean; busy: boolean }>()
const emit = defineEmits<{ 'update:preferences': [value: DebugPreferences]; save: []; apply: []; open: [] }>()
function toggle(enabled: boolean) { emit('update:preferences', { enabled, fullPayloads: enabled && props.preferences.fullPayloads }) }
</script>

<template>
  <section class="surface debug-preferences" :aria-label="t('debug.settings_title')">
    <div class="section-heading"><div><h2>{{ t('debug.settings_title') }}</h2><p>{{ t('debug.settings_description') }}</p></div><Bug :size="21"/></div>
    <ToggleRow :model-value="preferences.enabled" :label="t('debug.enabled')" :description="t('debug.enabled_hint')" :disabled="busy || !isDesktop" @update:model-value="toggle"/>
    <ToggleRow v-if="preferences.enabled" :model-value="preferences.fullPayloads" :label="t('debug.full_payloads')" :description="t('debug.full_payloads_hint')" :disabled="busy || !isDesktop" @update:model-value="emit('update:preferences', { ...preferences, fullPayloads: $event })"/>
    <p class="muted">{{ t(running ? 'debug.restart_hint' : 'debug.next_start_hint') }}</p>
    <div class="component-actions">
      <button class="button secondary" :disabled="busy || !changed || !isDesktop" @click="emit('save')">{{ t('debug.save') }}</button>
      <button v-if="running && (changed || pendingApply)" class="button primary" :disabled="busy || !isDesktop" @click="emit('apply')"><RefreshCw :size="14"/>{{ t('analysis.restart_apply') }}</button>
      <button class="text-button" :disabled="busy || !available || !isDesktop" @click="emit('open')">{{ t('debug.open') }}<ExternalLink :size="14"/></button>
    </div>
  </section>
</template>

<style scoped>
.debug-preferences .section-heading>svg{color:var(--accent)}.debug-preferences>.muted{font-size:12px;margin-top:14px}
</style>
