<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { LoaderCircle, Play, RefreshCw, Square, FileText, FolderOpen, ChevronRight, Info } from 'lucide-vue-next'
import { t } from '../i18n'
import { taskLabel } from '../domain/tasks'
import type { AnalysisPreferences } from '../domain/settings'
import type { AnalysisDiagnostics, AnalysisReport } from '../domain/analysis'
import { rpc, isDesktop } from '../services/desktop'
import { openPath } from '@tauri-apps/plugin-opener'
import ToggleRow from './ToggleRow.vue'
import AnalysisReportView from './AnalysisReportView.vue'
const props = defineProps<{ instanceId: string; ready: boolean; preferences: AnalysisPreferences; pendingApply: boolean; settingsBusy: boolean }>()
const emit = defineEmits<{ error: [message: string]; busy: [value: boolean]; 'update:preferences': [value: AnalysisPreferences]; save: []; apply: [] }>()
interface Source { name: string; saved_as: string; total_messages: number }
interface Task { task_id: string; status: string; progress: number; stage: string; detail?: string; error?: string; report?: unknown; diagnostics?: AnalysisDiagnostics }
type ReportName = 'timeline' | 'personality'
const reportKeys = { timeline: 'ui.relationship_timeline', personality: 'ui.personality_expression' } as const
const sources = ref<Source[]>([]), selected = ref<string[]>([])
const timeline = ref(true), personality = ref(true), resume = ref(true), since = ref('')
const task = ref<Task | null>(null), reports = ref<Partial<Record<ReportName, AnalysisReport>>>({}), reportName = ref<ReportName>('personality'), busy = ref('')
const diagnostics = ref<AnalysisDiagnostics | null>(null)
const activeTask = computed(() => !!task.value && !['done', 'failed', 'cancelled'].includes(task.value.status))
const shownReport = computed(() => reports.value[reportName.value])
const modelFailures = computed(() => (diagnostics.value?.model_responses ?? []).filter(item => item.reason !== 'ok').slice(-12))
const responseReasons = { empty: 'analysis.response_empty', reasoning_only: 'analysis.response_reasoning', output_limit: 'analysis.response_limit', incomplete: 'analysis.response_incomplete', refused: 'analysis.response_refused', http_error: 'analysis.response_http', unavailable: 'analysis.response_unavailable', invalid_response: 'analysis.response_invalid' } as const
function responseReason(reason: string) { return t(responseReasons[reason as keyof typeof responseReasons] ?? 'analysis.response_invalid') }
let alive = true, timer: ReturnType<typeof setTimeout> | undefined
let generation = 0, pollingGeneration: number | undefined
function call<T>(method: string, args: Record<string, unknown> = {}) { return rpc<T>(method, { ...args, instanceId: props.instanceId }) }
async function run(name: string, fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = name; if (name === 'start' || name === 'cancel') emit('busy', true)
  try { await fn() } catch (error) { if (alive) emit('error', error instanceof Error ? error.message : String(error)) }
  finally { busy.value = ''; if (name === 'start' || name === 'cancel') emit('busy', false) }
}
async function readDiagnostics(epoch = generation) {
  const result = await call<AnalysisDiagnostics>('analysis_diagnostics')
  if (alive && epoch === generation && !activeTask.value) {
    diagnostics.value = result
    syncPromptPreferences(result)
  }
  return result
}
async function readReport(name: ReportName, epoch = generation) {
  const value = await call<AnalysisReport>('analysis_report', { report: name })
  if (alive && epoch === generation && !activeTask.value) reports.value[name] = value
}
async function refreshReports(epoch = generation) {
  const result = await readDiagnostics(epoch)
  if (!alive || epoch !== generation || activeTask.value || !result.has_reports) return
  const names = (['timeline', 'personality'] as ReportName[]).filter(name => result.available_reports.includes(name))
  const results = await Promise.allSettled(names.map(name => readReport(name, epoch)))
  results.forEach((result) => { if (result.status === 'rejected' && alive && epoch === generation) emit('error', String(result.reason)) })
}
async function poll() {
  if (!task.value || !alive) return
  const epoch = generation, id = task.value.task_id
  if (pollingGeneration === epoch) return
  pollingGeneration = epoch
  clearTimeout(timer)
  try {
    const current = await call<Task>('analysis_status', { id })
    if (!alive || epoch !== generation || task.value?.task_id !== id) return
    task.value = current
    if (current.diagnostics) diagnostics.value = current.diagnostics
    if (activeTask.value) timer = setTimeout(poll, 1500)
    else await refreshReports(epoch)
  } catch (error) { if (alive && epoch === generation && task.value?.task_id === id) { emit('error', String(error)); if (activeTask.value) timer = setTimeout(poll, 4000) } }
  finally { if (pollingGeneration === epoch) pollingGeneration = undefined }
}
async function start(fresh = false) {
  await run('start', async () => {
    const epoch = ++generation
    clearTimeout(timer)
    const result = await call<Task>('analysis_start', { files: selected.value, timeline: timeline.value, personality: personality.value, resume: fresh ? false : resume.value, since: since.value })
    if (alive && epoch === generation) { task.value = result; reports.value = {}; diagnostics.value = null; void poll() }
  })
}
async function cancel() { await run('cancel', async () => { await call('analysis_cancel', { id: task.value?.task_id }); void poll() }) }
async function loadReport(name: ReportName) { reportName.value = name; if (!reports.value[name]) await run('report', () => readReport(name)) }
function syncPromptPreferences(result: AnalysisDiagnostics) {
  const next = {
    ...props.preferences,
    ...(result.prompt_ready?.personalityPrompt ? {} : { personalityPrompt: false }),
    ...(result.prompt_ready?.lifeContext ? {} : { lifeContext: false })
  }
  if (next.personalityPrompt !== props.preferences.personalityPrompt || next.lifeContext !== props.preferences.lifeContext) emit('update:preferences', next)
}
async function preference(key: keyof AnalysisPreferences, value: boolean) {
  if (!value) { emit('update:preferences', { ...props.preferences, [key]: false }); return }
  await run('check-artifacts', async () => {
    await readDiagnostics()
    if (!alive) return
    if (!diagnostics.value?.prompt_ready?.[key]) {
      emit('error', t(key === 'personalityPrompt' ? 'analysis.personality_required' : 'analysis.life_required'))
      return
    }
    emit('update:preferences', { ...props.preferences, [key]: true })
  })
}
async function openDiagnosticsDirectory() {
  const directory = diagnostics.value?.directory
  if (!directory || !isDesktop) return
  await run('open-diagnostics', async () => { await openPath(directory) })
}
async function load() {
  if (!isDesktop) return
  await run('load', async () => {
    const epoch = generation
    const state = await call<{ files: Source[]; task: Task | null }>('analysis_files')
    if (!alive || epoch !== generation) return
    sources.value = state.files; if (!selected.value.length) selected.value = state.files.map(file => file.saved_as); task.value = state.task
    if (props.ready && activeTask.value) void poll()
    else if (props.ready) await refreshReports(epoch)
    else await readDiagnostics(epoch)
  })
}
watch(() => props.ready, value => { if (value) void load() })
onMounted(load)
onUnmounted(() => { alive = false; clearTimeout(timer); emit('busy', false) })
</script>
<template>
  <div class="page-intro"><h1>{{ t('ui.advanced_analysis') }}</h1><p>{{ t('advanced.description') }}</p></div>
  <div v-if="!ready" class="inline-notice"><Info :size="17"/>{{ t('analysis.core_needed') }}</div>
  <section class="surface"><h2>{{ t('analysis.prompt_options') }}</h2><p class="muted">{{ t('analysis.prompt_notice') }}</p><ToggleRow :model-value="!!diagnostics?.prompt_ready?.personalityPrompt && preferences.personalityPrompt" :label="t('analysis.use_personality')" :description="t('analysis.use_personality_hint')" :disabled="settingsBusy || activeTask || !!busy || !diagnostics?.prompt_ready?.personalityPrompt" @update:model-value="preference('personalityPrompt', $event)"/><p v-if="!diagnostics?.prompt_ready?.personalityPrompt" class="analysis-prerequisite muted">{{ t('analysis.personality_required') }}</p><ToggleRow :model-value="!!diagnostics?.prompt_ready?.lifeContext && preferences.lifeContext" :label="t('analysis.use_life')" :description="t('analysis.use_life_hint')" :disabled="settingsBusy || activeTask || !!busy || !diagnostics?.prompt_ready?.lifeContext" @update:model-value="preference('lifeContext', $event)"/><p v-if="!diagnostics?.prompt_ready?.lifeContext" class="analysis-prerequisite muted">{{ t('analysis.life_required') }}</p><div class="component-actions"><button class="button secondary" :disabled="settingsBusy || activeTask || !isDesktop" @click="emit('save')">{{ t('analysis.save_preferences') }}</button><button v-if="pendingApply" class="button primary" :disabled="settingsBusy || activeTask || !isDesktop" @click="emit('apply')">{{ t('analysis.restart_apply') }}</button></div></section>
  <section class="surface analysis-task-surface">
    <h2>{{ t('analysis.new_task') }}</h2><p class="muted">{{ t('analysis.cost_notice') }}</p>
    <div class="analysis-options"><label><input v-model="timeline" type="checkbox" :disabled="activeTask"/>{{ t('ui.relationship_timeline') }}</label><label><input v-model="personality" type="checkbox" :disabled="activeTask"/>{{ t('ui.personality_expression') }}</label><label><input v-model="resume" type="checkbox" :disabled="activeTask"/>{{ t('analysis.resume') }}</label></div>
    <label>{{ t('analysis.since') }}<input v-model="since" type="date" :disabled="activeTask"/></label>
    <h3>{{ t('analysis.source_files') }}</h3><p v-if="!sources.length" class="muted">{{ t('analysis.no_files') }}</p>
    <label v-for="file in sources" :key="file.saved_as" class="analysis-source"><input v-model="selected" type="checkbox" :value="file.saved_as" :disabled="activeTask"/><FileText :size="16"/><span>{{ file.name }}<small>{{ file.total_messages }} {{ t('ui.messages') }}</small></span></label>
    <button class="button primary" :disabled="settingsBusy || !!busy || !isDesktop || !ready || activeTask || !selected.length || !(timeline || personality)" @click="start()"><LoaderCircle v-if="busy === 'start'" class="spinning" :size="14"/><Play v-else :size="14"/>{{ t('analysis.start') }}</button>
  </section>
  <section v-if="task" class="surface"><div class="section-heading"><h2>{{ t('analysis.progress') }}</h2><span class="pill">{{ task.status === 'done' && diagnostics?.state === 'empty' ? t('analysis.empty_status') : taskLabel(task.status) }}</span></div><p>{{ task.status === 'done' && diagnostics?.state === 'empty' ? t('analysis.no_findings') : task.stage }}</p><p v-if="task.detail" class="muted">{{ task.detail }}</p><progress :value="task.progress || 0" :max="1"/><p v-if="task.error" class="danger-text" role="alert">{{ task.error }}</p><div class="component-actions"><button class="button secondary" :disabled="!!busy || !ready" @click="poll"><RefreshCw :size="14"/>{{ t('analysis.refresh') }}</button><button v-if="activeTask" class="button secondary" :disabled="!!busy || !ready" @click="cancel"><Square :size="14"/>{{ t('analysis.cancel') }}</button></div><details v-if="task.report"><summary>{{ t('analysis.task_report') }}</summary><pre>{{ JSON.stringify(task.report, null, 2) }}</pre></details></section>
  <section v-if="!activeTask && busy !== 'start' && diagnostics && (diagnostics.has_reports || modelFailures.length)" class="surface"><h2>{{ t('analysis.result_quality') }}</h2><p :class="diagnostics.state !== 'available' ? 'danger-text' : 'muted'">{{ t(diagnostics.state === 'empty' ? 'analysis.empty_explanation' : diagnostics.state === 'partial' ? 'analysis.partial_explanation' : 'analysis.available_explanation') }}</p><dl class="report-stats"><div><dt>{{ t('analysis.blocks') }}</dt><dd>{{ diagnostics.completed }} / {{ diagnostics.blocks }}</dd></div><div><dt>{{ t('analysis.skipped_blocks') }}</dt><dd>{{ diagnostics.skipped }}</dd></div><div><dt>{{ t('analysis.findings') }}</dt><dd>{{ diagnostics.events }} / {{ diagnostics.observations }}</dd></div></dl><p class="muted">{{ t('analysis.cache_notice') }}</p><button class="button secondary" :disabled="settingsBusy || activeTask || !ready || !selected.length || !(timeline || personality)" @click="start(true)"><RefreshCw :size="14"/>{{ t('analysis.retry_fresh') }}</button><div v-if="modelFailures.length" class="analysis-model-errors"><h3>{{ t('analysis.model_diagnostics') }}</h3><p class="muted">{{ t('analysis.model_diagnostics_hint') }}</p><article v-for="(response, index) in modelFailures" :key="index" class="report-entry"><strong>{{ responseReason(response.reason) }}</strong><p class="muted">{{ t('analysis.response_metadata', { protocol: response.protocol ?? '—', finish: response.finish_reason ?? '—', budget: response.requested_tokens ?? '—', output: response.completion_tokens ?? '—', reasoning: response.reasoning_tokens ?? '—' }) }}<span v-if="response.http_status"> · HTTP {{ response.http_status }}</span></p></article></div><details class="analysis-disclosure"><summary class="button secondary analysis-disclosure-toggle">{{ t('analysis.diagnostics') }}<ChevronRight :size="15"/></summary><div class="diagnostics-actions"><button class="button secondary" :disabled="!isDesktop || !!busy" @click="openDiagnosticsDirectory"><FolderOpen :size="14"/>{{ t('analysis.open_diagnostics_directory') }}</button></div><p class="muted">{{ diagnostics.directory }}</p><p v-if="!diagnostics.failures.length">{{ t('analysis.no_recorded_error') }}</p><article v-for="failure in diagnostics.failures" :key="failure.block_id" class="report-entry"><strong>{{ failure.block_id }}</strong><p>{{ failure.message }}</p><small>{{ failure.stage }}</small><p v-for="(attempt, index) in failure.attempts" :key="index">{{ attempt.error }} <span v-if="attempt.output_empty">{{ t('analysis.model_output_empty') }}</span></p></article></details></section>
  <section class="surface"><h2>{{ t('analysis.saved_reports') }}</h2><p class="muted">{{ t('analysis.report_notice') }}</p><details class="saved-report-details"><summary class="button secondary analysis-disclosure-toggle">{{ t('analysis.expand_saved_reports') }}<ChevronRight :size="15"/></summary><div class="component-actions" role="group" :aria-label="t('analysis.saved_reports')"><button v-for="(key, name) in reportKeys" :key="name" class="button" :class="reportName === name ? 'primary' : 'secondary'" :aria-pressed="reportName === name" :disabled="!!busy || !ready || activeTask" @click="loadReport(name)">{{ t(key) }}</button></div><AnalysisReportView v-if="!activeTask && busy !== 'start' && shownReport" :report="shownReport" :name="t(reportKeys[reportName])"/></details></section>
</template>

<style scoped>
.analysis-prerequisite{font-size:12px;margin:-4px 0 14px;line-height:1.8}
.analysis-task-surface{margin-top:34px}
.analysis-disclosure{margin-top:18px}
.analysis-disclosure-toggle{width:fit-content;max-width:100%;white-space:normal;text-align:left}
.analysis-disclosure-toggle:hover{border-color:#af9e84;background:#fbf8ef}
.analysis-disclosure-toggle:focus-visible{outline:2px solid #94764e;outline-offset:3px}
.analysis-disclosure-toggle svg{flex-shrink:0;transition:transform .15s}
.saved-report-details{margin-top:16px}
.diagnostics-actions{display:flex;justify-content:flex-end;margin:10px 0 14px}
</style>
