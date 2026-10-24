<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Bug, Check, Clipboard, LoaderCircle, RefreshCw, Search, Trash2, X } from 'lucide-vue-next'
import type { DebugSnapshot, ProactivePreview, SearchResult } from '../domain/debug'
import { locale, t } from '../i18n'
import { rpc } from '../services/desktop'

const props = defineProps<{ instanceId: string; conversationId?: string; initialQuery: string; fullPayloads: boolean; externalBusy: boolean }>()
const emit = defineEmits<{ close: []; busy: [value: boolean] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const snapshot = ref<DebugSnapshot | null>(null), results = ref<SearchResult | null>(null), preview = ref<ProactivePreview | null>(null)
const tabs = ['overview', 'calls', 'retrieval', 'life', 'config'] as const
type Tab = typeof tabs[number]
const tab = ref<Tab>('overview')
const tabKeys = { overview: 'debug.overview', calls: 'debug.calls', retrieval: 'debug.retrieval', life: 'debug.life', config: 'debug.config' } as const
const memoryKeys = { friend_messages: 'debug.friend_messages', dialogue_windows: 'debug.dialogue_windows', response_pairs: 'debug.response_pairs', history_images: 'debug.history_images', live_messages: 'debug.live_messages', relationship_memories: 'debug.relationship_memories' } as const
const groups = [
  { key: 'fused', label: 'debug.fused' }, { key: 'response_pairs', label: 'debug.response_pairs' },
  { key: 'friend_examples', label: 'debug.friend_messages' }, { key: 'dialogue_windows', label: 'debug.dialogue_windows' },
  { key: 'history_images', label: 'debug.history_images' }, { key: 'recent_live', label: 'debug.live_messages' },
] as const
const query = ref(props.initialQuery.slice(0, 4000)), topK = ref(12), topic = ref(''), context = ref('')
const autoRefresh = ref(false), refreshing = ref(false), operation = ref(''), error = ref(''), copied = ref(false), confirmReset = ref(false)
const updated = ref<number | null>(null)
let alive = true, timer: ReturnType<typeof setTimeout> | undefined, copiedTimer: ReturnType<typeof setTimeout> | undefined
const modelCalls = computed(() => [...(snapshot.value?.stats.model_chain ?? [])].reverse())
const totalCalls = computed(() => Object.values(snapshot.value?.stats.calls ?? {}).reduce((sum, item) => sum + item.count, 0))
const totalErrors = computed(() => Object.values(snapshot.value?.stats.calls ?? {}).reduce((sum, item) => sum + item.error_count, 0))
const previewText = computed(() => preview.value?.silenced ? undefined : typeof preview.value?.message === 'string' ? preview.value.message : preview.value?.message?.content)
function pretty(value: unknown) { return JSON.stringify(value, null, 2) ?? '' }
function time(value: number) { return new Intl.DateTimeFormat(locale.value, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(value) }
function number(value: number | undefined) { return typeof value === 'number' ? new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(value) : '—' }
function call<T>(method: string, args: Record<string, unknown> = {}) { return rpc<T>(method, { ...args, instanceId: props.instanceId }) }
function message(value: unknown) { return value instanceof Error ? value.message : String(value) }
function close() { if (!operation.value) emit('close') }
function schedule() { clearTimeout(timer); if (alive && autoRefresh.value) timer = setTimeout(refresh, 5000) }
async function refresh() {
  if (refreshing.value || operation.value || !alive) return
  refreshing.value = true
  try {
    const value = await call<DebugSnapshot>('debug_snapshot')
    if (alive) { snapshot.value = value; updated.value = Date.now(); error.value = '' }
  } catch (e) { if (alive) error.value = message(e) }
  finally { refreshing.value = false; schedule() }
}
function setAutoRefresh(value: boolean) { autoRefresh.value = value; if (value) void refresh(); else clearTimeout(timer) }
async function run(name: string, fn: () => Promise<void>) {
  if (operation.value || refreshing.value || props.externalBusy) return
  clearTimeout(timer)
  operation.value = name; error.value = ''; copied.value = false; emit('busy', true)
  try { await fn() } catch (e) { if (alive) error.value = message(e) }
  finally { operation.value = ''; emit('busy', false); schedule() }
}
async function search() {
  await run('search', async () => {
    results.value = null
    const value = await call<SearchResult>('debug_search', { query: query.value, topK: topK.value, conversationId: props.conversationId })
    if (alive) results.value = value
  })
}
async function generatePreview() {
  await run('proactive', async () => {
    preview.value = null
    const value = await call<ProactivePreview>('debug_proactive', { conversationId: props.conversationId, topic_hint: topic.value, private_context: context.value })
    if (alive) preview.value = value
  })
}
async function reset() {
  let completed = false
  await run('reset', async () => { await call('debug_reset_metrics'); completed = true; if (alive) { confirmReset.value = false; snapshot.value = null } })
  if (alive && completed) await refresh()
}
async function copy() {
  if (!snapshot.value) return
  try {
    await navigator.clipboard.writeText(pretty({ ...snapshot.value, ...(results.value ? { retrieval: results.value } : {}), ...(preview.value ? { proactive_preview: preview.value } : {}) }))
    if (alive) { copied.value = true; clearTimeout(copiedTimer); copiedTimer = setTimeout(() => { copied.value = false }, 2000) }
  } catch { if (alive) error.value = t('debug.copy_failed') }
}
onMounted(() => { dialog.value?.showModal(); void refresh() })
onUnmounted(() => { alive = false; clearTimeout(timer); clearTimeout(copiedTimer); dialog.value?.close(); emit('busy', false) })
</script>

<template>
  <dialog ref="dialog" class="debug-drawer" aria-labelledby="debug-title" @cancel.prevent="close" @click.self="close">
    <div class="debug-shell">
      <header class="debug-heading"><div><span class="eyebrow"><Bug :size="14"/>{{ t('debug.eyebrow') }}</span><h2 id="debug-title">{{ t('debug.title') }}</h2><p>{{ t(conversationId ? 'debug.current_conversation' : 'debug.instance_scope') }}</p></div><button class="icon-button" autofocus :disabled="!!operation" :aria-label="t('common.close')" @click="close"><X :size="20"/></button></header>
      <div class="debug-toolbar"><button class="button secondary" :disabled="refreshing || !!operation" @click="refresh"><LoaderCircle v-if="refreshing" :size="14" class="spinning"/><RefreshCw v-else :size="14"/>{{ t('analysis.refresh') }}</button><label><input type="checkbox" :checked="autoRefresh" @change="setAutoRefresh(($event.target as HTMLInputElement).checked)"/>{{ t('debug.auto_refresh') }}</label><button class="text-button" :disabled="!snapshot || !!operation" @click="copy"><Check v-if="copied" :size="14"/><Clipboard v-else :size="14"/>{{ t(copied ? 'debug.copied' : 'debug.copy') }}</button><small v-if="updated">{{ t('debug.updated', { time: time(updated) }) }}</small></div>
      <nav class="debug-tabs" :aria-label="t('debug.sections')"><button v-for="item in tabs" :key="item" :aria-pressed="tab === item" :class="{ selected: tab === item }" @click="tab = item">{{ t(tabKeys[item]) }}</button></nav>
      <p v-if="error" class="debug-error" role="alert">{{ error }}</p>
      <div class="debug-body" :aria-busy="refreshing || !!operation">
        <template v-if="tab === 'overview'">
          <template v-if="snapshot">
            <div class="debug-summary"><div><small>{{ t('debug.core_version') }}</small><strong>{{ snapshot.stats.version }}</strong></div><div><small>{{ t('debug.call_count') }}</small><strong>{{ number(totalCalls) }}</strong></div><div><small>{{ t('debug.error_count') }}</small><strong :class="{ 'danger-text': totalErrors }">{{ number(totalErrors) }}</strong></div></div>
            <h3>{{ t('debug.memory_counts') }}</h3><dl class="debug-key-values"><div v-for="(key, name) in memoryKeys" :key="name"><dt>{{ t(key) }}</dt><dd>{{ number(snapshot.stats.memory[name]) }}</dd></div></dl>
            <h3>{{ t('debug.database') }}</h3><p class="debug-note">{{ t('debug.database_hint') }}</p><details v-for="(value, key) in snapshot.stats.database" :key="key"><summary>{{ key }}</summary><pre>{{ pretty(value) }}</pre></details>
            <details><summary>{{ t('debug.writeback') }}</summary><pre>{{ pretty(snapshot.stats.writeback) }}</pre></details><details><summary>{{ t('debug.proactive_state') }}</summary><pre>{{ pretty(snapshot.stats.proactive) }}</pre></details>
            <div class="debug-reset"><button class="text-button danger-text" :disabled="!!operation || refreshing || externalBusy" @click="confirmReset = !confirmReset"><Trash2 :size="14"/>{{ t('debug.reset') }}</button><div v-if="confirmReset"><p>{{ t('debug.reset_hint') }}</p><button class="button secondary" :disabled="!!operation || refreshing || externalBusy" @click="reset">{{ t('debug.confirm_reset') }}</button><button class="text-button" :disabled="!!operation" @click="confirmReset = false">{{ t('common.cancel') }}</button></div></div>
          </template><p v-else class="debug-note">{{ t(refreshing ? 'debug.loading' : 'debug.no_snapshot') }}</p>
        </template>
        <template v-else-if="tab === 'calls'">
          <p class="debug-note">{{ t(fullPayloads ? 'debug.payloads_recording' : 'debug.payloads_not_recorded') }}</p>
          <div v-if="snapshot && Object.keys(snapshot.stats.calls).length" class="debug-table-wrap"><table><thead><tr><th>{{ t('debug.stage') }}</th><th>{{ t('debug.call_count') }}</th><th>{{ t('debug.error_count') }}</th><th>{{ t('debug.average_ms') }}</th><th>P50 · ms</th><th>P95 · ms</th></tr></thead><tbody><tr v-for="(item, key) in snapshot.stats.calls" :key="key"><td>{{ key }}</td><td>{{ item.count }}</td><td>{{ item.error_count }}</td><td>{{ number(item.avg_latency_ms) }}</td><td>{{ number(item.p50_latency_ms) }}</td><td>{{ number(item.p95_latency_ms) }}</td></tr></tbody></table></div>
          <h3>{{ t('debug.model_chain') }}</h3><p v-if="!modelCalls.length" class="debug-note">{{ t('debug.no_calls') }}</p>
          <details v-for="(item, index) in modelCalls" :key="item.trace_id + ':' + item.ts_ms + ':' + index" class="debug-call"><summary><span><strong>{{ item.stage }} · {{ item.model }}</strong><small>{{ time(item.ts_ms) }} · {{ item.status }} · {{ number(item.latency_ms) }} ms</small></span></summary><dl class="debug-key-values"><div><dt>Trace ID</dt><dd>{{ item.trace_id }}</dd></div><div><dt>{{ t('debug.attempt') }}</dt><dd>{{ item.attempt }}</dd></div><div><dt>HTTP</dt><dd>{{ item.status_code ?? '—' }}</dd></div></dl><p class="debug-note">{{ item.url }}</p><p v-if="item.error" class="danger-text">{{ item.error }}</p><details v-if="fullPayloads"><summary>{{ t('debug.request') }}</summary><pre>{{ pretty(item.request) }}</pre></details><details v-if="fullPayloads"><summary>{{ t('debug.response') }}</summary><pre>{{ pretty(item.response) }}</pre></details></details>
        </template>
        <template v-else-if="tab === 'retrieval'">
          <p class="debug-note">{{ t('debug.retrieval_hint') }}</p><form class="debug-form" @submit.prevent="search"><label>{{ t('debug.query') }}<textarea v-model="query" maxlength="4000" rows="3" required :disabled="!!operation"/></label><div class="debug-form-row"><label>{{ t('debug.top_k') }}<input v-model.number="topK" type="number" min="1" max="50" step="1" required :disabled="!!operation"/></label><button class="button primary" :disabled="!!operation || refreshing || externalBusy || !query.trim()"><LoaderCircle v-if="operation === 'search'" :size="14" class="spinning"/><Search v-else :size="14"/>{{ t('debug.search') }}</button></div></form>
          <template v-if="results"><p v-if="results.trace_id" class="debug-note">Trace ID · {{ results.trace_id }}</p><section v-for="group in groups" :key="group.key" class="debug-hit-group"><h3>{{ t(group.label) }}<small>{{ results[group.key]?.length ?? 0 }}</small></h3><p v-if="!results[group.key]?.length" class="debug-note">{{ t('debug.no_hits') }}</p><article v-for="(hit, index) in results[group.key]" :key="hit.chunk_id + ':' + index" class="debug-hit"><small>#{{ hit.rank ?? index + 1 }} · {{ t('debug.score') }} {{ number(hit.score) }}<template v-if="hit.sender_name"> · {{ hit.sender_name }}</template></small><p>{{ hit.text }}</p><details><summary>{{ t('debug.hit_details') }}</summary><pre>{{ pretty(hit) }}</pre></details></article></section></template>
        </template>
        <template v-else-if="tab === 'life'">
          <h3>{{ t('debug.life_snapshot') }}</h3><dl v-if="snapshot?.stats.life.snapshot" class="debug-key-values"><div v-for="(value, key) in snapshot.stats.life.snapshot" :key="key"><dt>{{ key }}</dt><dd>{{ typeof value === 'object' ? pretty(value) : value }}</dd></div></dl><details><summary>{{ t('debug.daily_plan') }}</summary><pre>{{ pretty(snapshot?.stats.life.daily_plan) }}</pre></details><details><summary>{{ t('debug.recent_timeline') }}</summary><pre>{{ pretty(snapshot?.stats.life.recent_timeline) }}</pre></details>
          <h3>{{ t('debug.proactive_preview') }}</h3><p class="debug-note">{{ t('debug.proactive_hint') }}</p><p v-if="!conversationId" class="debug-note">{{ t('debug.conversation_required') }}</p><form v-else class="debug-form" @submit.prevent="generatePreview"><label>{{ t('debug.topic') }}<input v-model="topic" maxlength="2000" :disabled="!!operation"/></label><label>{{ t('debug.context') }}<textarea v-model="context" rows="3" maxlength="8000" :disabled="!!operation"/></label><button class="button secondary" :disabled="!!operation || refreshing || externalBusy"><LoaderCircle v-if="operation === 'proactive'" :size="14" class="spinning"/>{{ t('debug.generate_preview') }}</button></form>
          <article v-if="preview" class="debug-preview"><p>{{ previewText || t(preview.silenced ? 'debug.preview_silenced' : 'debug.preview_empty') }}</p><details><summary>{{ t('debug.preview_details') }}</summary><pre>{{ pretty(preview) }}</pre></details></article>
        </template>
        <template v-else><p class="debug-note">{{ t('debug.config_hint') }}</p><pre v-if="snapshot">{{ pretty(snapshot.config) }}</pre></template>
        <p class="debug-privacy">{{ t('debug.privacy') }}</p>
      </div>
    </div>
  </dialog>
</template>

<style scoped>
.debug-drawer{position:fixed;inset:0 0 0 auto;width:min(820px,100vw);height:100%;max-width:100vw;max-height:100%;margin:0;padding:0;border:0;border-left:1px solid var(--line);background:var(--paper);color:var(--ink);box-shadow:-12px 0 50px #1a2f4b15}.debug-drawer::backdrop{background:#1a2f4b4d}.debug-shell{height:100%;display:flex;flex-direction:column}.debug-heading{padding:28px 30px 18px;display:flex;justify-content:space-between;gap:16px}.debug-heading .eyebrow{display:flex;align-items:center;gap:8px}.debug-heading h2{font-size:26px;margin:10px 0 5px}.debug-heading p{color:var(--muted);font-size:12px}.debug-toolbar{display:flex;align-items:center;flex-wrap:wrap;gap:14px;padding:0 30px 20px}.debug-toolbar label{display:flex;align-items:center;gap:7px;font-size:12px}.debug-toolbar small{font-size:10px;color:var(--muted)}.debug-toolbar input{accent-color:var(--accent)}.debug-tabs{display:flex;padding:0 25px;border-block:1px solid var(--line);overflow-x:auto;flex-shrink:0}.debug-tabs>button{padding:15px 13px;background:transparent;border-bottom:2px solid transparent;font-size:12px;white-space:nowrap}.debug-tabs>button.selected{color:var(--accent);border-bottom-color:var(--accent)}.debug-body{flex:1;overflow:auto;min-height:0;padding:24px 30px 32px}.debug-body h3{font-size:14px;margin:24px 0 12px}.debug-body>h3:first-child{margin-top:0}.debug-note{color:var(--muted);font-size:12px;overflow-wrap:anywhere;margin:8px 0 16px}.debug-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin-bottom:26px;border-bottom:1px solid var(--line);padding-bottom:22px}.debug-summary small,.debug-summary strong{display:block}.debug-summary small{font-size:11px;color:var(--muted);margin-bottom:8px}.debug-summary strong{font-size:24px;font-weight:500;font-variant-numeric:tabular-nums}.debug-key-values{margin:0 0 20px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:15px 25px}.debug-key-values div{min-width:0}.debug-key-values dt{font-size:11px;color:var(--muted)}.debug-key-values dd{margin:5px 0 0;font-size:13px;overflow-wrap:anywhere;white-space:pre-wrap}.debug-body pre{font-size:11px;line-height:1.8;padding:15px;background:#ede8da75;border:1px solid var(--line);border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto;user-select:text}.debug-body details{border-top:1px solid var(--line);padding:13px 0}.debug-body summary{cursor:pointer;font-size:12px;line-height:1.8}.debug-body details details{margin-top:10px}.debug-call summary>span{display:inline-grid;gap:3px;vertical-align:top;max-width:90%}.debug-call summary strong{font-weight:500;overflow-wrap:anywhere}.debug-call summary small{color:var(--muted);font-size:10px}.debug-call>.debug-key-values{margin-top:18px}.debug-table-wrap{overflow-x:auto}.debug-table-wrap table{width:100%;border-collapse:collapse;font-size:11px;text-align:right}.debug-table-wrap th,.debug-table-wrap td{padding:12px 9px;border-bottom:1px solid var(--line);white-space:nowrap}.debug-table-wrap th{font-weight:500;color:var(--muted)}.debug-table-wrap th:first-child,.debug-table-wrap td:first-child{text-align:left}.debug-reset{margin-top:28px}.debug-reset>div{padding:14px 0}.debug-reset p{font-size:12px;margin-bottom:12px}.debug-reset .button{margin-right:14px}.debug-form{display:grid;gap:16px;margin:18px 0 25px}.debug-form>label,.debug-form-row>label{display:grid;gap:8px;font-size:12px}.debug-form textarea{width:100%;resize:vertical}.debug-form-row{display:flex;align-items:flex-end;gap:18px}.debug-form-row input{width:100px}.debug-form>button{justify-self:start}.debug-hit-group{margin-top:28px}.debug-hit-group h3{display:flex;align-items:center;gap:10px}.debug-hit-group h3 small{font-size:11px;color:var(--muted)}.debug-hit{border-top:1px solid var(--line);padding:14px 0}.debug-hit>small{font-size:10px;color:var(--muted)}.debug-hit>p,.debug-preview>p{font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 16px}.debug-error{padding:12px 30px;color:#a03726;background:#a0372608;font-size:12px;overflow-wrap:anywhere}.debug-privacy{font-size:10px;line-height:1.8;color:var(--muted);margin-top:32px;padding-top:18px;border-top:1px solid var(--line)}@media(max-width:600px){.debug-heading{padding:22px 18px 16px}.debug-toolbar{padding:0 18px 16px;gap:10px}.debug-tabs{padding:0 10px}.debug-body{padding:20px 18px}.debug-summary strong{font-size:20px}.debug-key-values{grid-template-columns:1fr}.debug-error{padding:12px 18px}}
</style>
