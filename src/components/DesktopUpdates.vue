<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Download, LoaderCircle, RefreshCw } from 'lucide-vue-next'
import { invoke } from '@tauri-apps/api/core'
import { currentInstanceId, isDesktop, rpc, type Result } from '../services/desktop'
import { locale, t } from '../i18n'

const props = defineProps<{ busy: boolean }>()
const emit = defineEmits<{ busy: [value: boolean]; refreshed: []; notice: [message: string, error: boolean]; availability: [value: boolean] }>()
interface Status { currentVersion: string; availableVersion: string | null; available: boolean; sourceUrl: string; latestVersion?: string | null; releasePending?: boolean }
const status = ref<Status | null>(null)
const source = ref('')
const working = ref(false)
const confirmInstall = ref(false)
async function refresh() {
  status.value = await rpc<Status>('desktop_update_status')
  source.value = status.value.sourceUrl
  emit('availability', status.value.available === true)
}
async function run(task: () => Promise<void>) {
  if (props.busy || working.value) return
  working.value = true; emit('busy', true)
  try { await task() } catch (error) { emit('notice', error instanceof Error ? error.message : String(error), true) }
  finally { working.value = false; emit('busy', false) }
}
async function check() { await run(async () => { const result = await rpc<Result>('refresh_catalog', { url: source.value.trim() }); await refresh(); confirmInstall.value = false; emit('refreshed'); emit('notice', result.message, !result.ok) }) }
async function applyStaged() { await invoke('apply_desktop_update', { args: { instanceId: currentInstanceId.value, locale: locale.value } }) }
async function install() { await run(async () => {
  await rpc('download_desktop_update')
  await applyStaged()
}) }
onMounted(async () => { if (isDesktop) { try { await refresh() } catch (error) { emit('availability', false); emit('notice', String(error), true) } } })
</script>
<template>
  <section class="desktop-updates surface">
    <div class="section-heading"><div><h2>{{ t('updates.desktop_title') }}</h2><p>{{ t('updates.bundled_extensions') }}</p></div><span v-if="status" class="pill">{{ status.currentVersion }}</span></div>
    <p class="muted">{{ status?.available ? t('updates.available_version', { version: status.availableVersion ?? '' }) : status?.releasePending ? t('updates.release_pending', { version: status.latestVersion ?? '' }) : t('updates.desktop_no_release') }}</p>
    <details class="update-source"><summary>{{ t('updates.source') }}</summary><label>{{ t('updates.catalog_url') }}<input v-model="source" type="url" placeholder="https://github.com/kldhsh123/Afterglow-Desktop/releases/latest/download/catalog.json" :disabled="busy || working || !isDesktop"/></label><p class="muted">{{ t('updates.source_hint') }}</p></details>
    <div class="component-actions"><button class="button secondary" :disabled="busy || working || !isDesktop" @click="check"><LoaderCircle v-if="working" :size="14" class="spinning"/><RefreshCw v-else :size="14"/>{{ t('updates.check') }}</button><button v-if="status?.available && !confirmInstall" class="button primary" :disabled="busy || working" @click="confirmInstall = true"><Download :size="14"/>{{ t('updates.desktop_install') }}</button></div>
    <div v-if="confirmInstall" class="inline-notice"><p>{{ t('updates.close_notice') }}</p><button class="button secondary" :disabled="working" @click="confirmInstall = false">{{ t('common.cancel') }}</button><button class="button primary" :disabled="busy || working" @click="install"><LoaderCircle v-if="working" :size="14" class="spinning"/>{{ t(working ? 'updates.downloading' : 'updates.download_and_exit') }}</button></div>
  </section>
</template>
