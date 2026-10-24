<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { FolderOpen, ImagePlus, LoaderCircle, Square } from 'lucide-vue-next'
import { t } from '../i18n'
import { chooseDirectory, isDesktop, rpc } from '../services/desktop'
const props = defineProps<{ instanceId: string; ready: boolean; visionEnabled: boolean; disabled: boolean }>()
const emit = defineEmits<{ error: [message: string]; busy: [value: boolean]; 'core-change': [] }>()
const metricKeys = ['total_refs', 'matched_files', 'missing_files', 'unique_images', 'described_images', 'reused_descriptions', 'skipped_failed_descriptions', 'skipped_existing_rows', 'upserted_rows'] as const
type Metric = typeof metricKeys[number]
const labels = { total_refs: 'media.refs', matched_files: 'media.matched', missing_files: 'media.missing', unique_images: 'media.unique', described_images: 'media.described', reused_descriptions: 'media.reused', skipped_failed_descriptions: 'media.failed_images', skipped_existing_rows: 'media.existing', upserted_rows: 'media.upserted' } as const
interface Task { id: string; status: string; directory: string; report: Record<Metric, number> | null; error: string; restart_error: string }
const task = ref<Task | null>(null), directory = ref(''), working = ref(false)
const active = computed(() => !!task.value && !['done', 'failed', 'cancelled'].includes(task.value.status))
let alive = true, timer: ReturnType<typeof setTimeout> | undefined
function call<T>(method: string, args: Record<string, unknown> = {}) { return rpc<T>(method, { ...args, instanceId: props.instanceId }) }
async function run(fn: () => Promise<void>) {
  if (working.value || props.disabled) return
  working.value = true; emit('busy', true)
  try { await fn() } catch (error) { if (alive) emit('error', error instanceof Error ? error.message : String(error)) }
  finally { working.value = false; emit('busy', false) }
}
async function poll() {
  clearTimeout(timer)
  try {
    const result = await call<Task | null>('history_images_status')
    if (!alive) return
    const wasActive = active.value
    task.value = result
    if (result && !directory.value) directory.value = result.directory
    if (wasActive && !active.value) emit('core-change')
    if (active.value) timer = setTimeout(poll, 1500)
  } catch (error) { if (alive) { emit('error', String(error)); if (active.value) timer = setTimeout(poll, 4000) } }
}
async function choose() { await run(async () => { const selected = await chooseDirectory(); if (alive && selected) directory.value = selected }) }
async function start() { await run(async () => { const value = await call<Task>('history_images_start', { directory: directory.value }); if (alive) { task.value = value; emit('core-change'); void poll() } }) }
async function cancel() { await run(async () => { await call('history_images_cancel'); void poll() }) }
onMounted(() => { if (isDesktop) void poll() })
onUnmounted(() => { alive = false; clearTimeout(timer); emit('busy', false) })
</script>
<template><section class="surface"><div class="section-heading"><div><h2>{{ t('media.title') }}</h2><p class="muted">{{ t('media.description') }}</p></div><ImagePlus :size="23"/></div><p class="muted">{{ t('media.notice') }}</p><p v-if="!visionEnabled" class="inline-notice">{{ t('media.vision_required') }}</p><div class="component-actions"><button class="button secondary" :disabled="working || disabled || active || !isDesktop" @click="choose"><FolderOpen :size="15"/>{{ t('media.choose_directory') }}</button><button class="button primary" :disabled="working || disabled || active || !ready || !visionEnabled || !directory || !isDesktop" @click="start"><ImagePlus :size="15"/>{{ t('media.start') }}</button><button v-if="active && task?.status !== 'restoring'" class="button secondary" :disabled="working || disabled" @click="cancel"><Square :size="14"/>{{ t('media.cancel') }}</button></div><p v-if="directory" class="selected-directory">{{ directory }}</p><div v-if="task" class="media-task" aria-live="polite"><p><LoaderCircle v-if="active" :size="15" class="spinning"/>{{ t(task.status === 'restoring' ? 'media.restoring' : task.status === 'running' ? 'media.running' : task.status === 'done' ? 'media.done' : task.status === 'cancelled' ? 'media.cancelled' : 'media.failed') }}</p><p v-if="task.error" class="danger-text">{{ task.error }}</p><p v-if="task.restart_error" class="danger-text">{{ t('media.restart_error', { reason: task.restart_error }) }}</p><dl v-if="task.report" class="report-stats"><div v-for="key in metricKeys" :key="key"><dt>{{ t(labels[key]) }}</dt><dd>{{ task.report[key] }}</dd></div></dl><p v-if="task.report && !task.report.total_refs" class="inline-notice">{{ t('media.no_refs') }}</p><p v-if="task.report?.missing_files" class="inline-notice">{{ t('media.missing_notice') }}</p></div></section></template>
