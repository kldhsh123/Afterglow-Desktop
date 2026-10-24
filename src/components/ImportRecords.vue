<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, Check, FileText, FolderOpen, Info, LoaderCircle, RefreshCw, ScanText, ShieldCheck, Upload, UsersRound, Feather, X } from 'lucide-vue-next'
import { t } from '../i18n'
import { isDesktop } from '../services/desktop'
import { taskLabel } from '../domain/tasks'
import type { Candidate, ImportedFile, ImportTask, PreviewFile } from '../domain/imports'
import { summarizeImport } from '../domain/imports'
const props = defineProps<{ files: ImportedFile[]; previewFiles: PreviewFile[]; candidates: Candidate[]; selfUids: string[]; friendUids: string[]; task: ImportTask | null; dragover: boolean; busy: string; ready: boolean; identitySelectionValid: boolean; recovery: 'idle' | 'restarting' | 'waiting' | 'ready' | 'failed'; recoveryError: string }>()
const emit = defineEmits<{ pick: []; preview: [files: PreviewFile[]]; drop: [event: DragEvent]; drag: [value: boolean]; removeFile: [index: number]; removePreview: [index: number]; reanalyze: [file: ImportedFile]; 'update:selfUids': [value: string[]]; 'update:friendUids': [value: string[]]; start: []; cancel: []; manageCore: []; retryCore: [] }>()
const fileInput = ref<HTMLInputElement | null>(null)
const importing = computed(() => !!props.task && !['done', 'completed', 'failed', 'cancelled'].includes(props.task.status))
const completed = computed(() => !!props.task && ['done', 'completed'].includes(props.task.status))
const summary = computed(() => summarizeImport(props.task?.report))
const recovering = computed(() => props.recovery === 'restarting' || props.recovery === 'waiting')
const selectionLocked = computed(() => !!props.busy || importing.value || completed.value || recovering.value)
const missingIdentities = computed(() => props.files.filter(file => !file.error && file.format !== 'unknown' &&
  (!file.candidates.some(candidate => props.selfUids.includes(candidate.uid)) ||
   !file.candidates.some(candidate => props.friendUids.includes(candidate.uid)))))
const flowStage = computed(() => completed.value ? 4 : props.task ? 3 : props.candidates.length ? 2 : props.busy === 'inspect' ? 1 : 0)
const flow = computed(() => [
  { label: t('import.flow_files'), icon: FolderOpen },
  { label: t('import.flow_format'), icon: ScanText },
  { label: t('import.flow_people'), icon: UsersRound },
  { label: t('import.flow_memories'), icon: Feather },
])
function pickFiles() { if (isDesktop) emit('pick'); else fileInput.value?.click() }
function previewSelection(event: Event) {
  const input = event.target as HTMLInputElement
  emit('preview', Array.from(input.files ?? []).map(file => ({ name: file.name, size: file.size })))
  input.value = ''
}
function formatSize(size: number) { return size < 1024 * 1024 ? (size / 1024).toFixed(1) + ' KB' : (size / 1024 / 1024).toFixed(1) + ' MB' }
function accountFiles(uid: string) { return props.files.filter(file => file.candidates.some(candidate => candidate.uid === uid)).map(file => file.name).join(' · ') }
function selectIdentity(side: 'self' | 'friend', uid: string, checked: boolean) {
  const current = side === 'self' ? props.selfUids : props.friendUids
  const selected = checked ? [...new Set([...current, uid])] : current.filter(value => value !== uid)
  if (side === 'self') emit('update:selfUids', selected)
  else emit('update:friendUids', selected)
}
</script>
<template>
  <div class="import-records" :class="{ 'has-files': files.length || previewFiles.length }">
    <ol class="import-flow" :aria-label="t('import.flow_label')">
      <li v-for="(item, index) in flow" :key="index" :class="{ current: flowStage === index, complete: flowStage > index, working: (busy === 'inspect' && index === 1) || (importing && index === 3) }" :aria-current="flowStage === index ? 'step' : undefined">
        <span class="import-flow-icon"><Check v-if="flowStage > index" :size="17"/><component v-else :is="item.icon" :size="18" :stroke-width="1.5"/></span><span>{{ item.label }}</span><i v-if="index < flow.length - 1" aria-hidden="true"/>
      </li>
    </ol>
    <input ref="fileInput" type="file" hidden multiple accept=".json,.jsonl,.ndjson,.txt,.md,.html,.htm" @change="previewSelection"/>
          <div v-if="!ready && !importing && !recovering && recovery !== 'failed'" class="inline-notice"><Info :size="17"/><span>{{ t('ui.start_the_original_core_to_detect_formats') }}</span><button class="text-button" @click="emit('manageCore')">{{ t('ui.manage_core') }}<ArrowRight :size="14"/></button></div>
          <div class="dropzone" :class="{ dragging: dragover }" @dragover.prevent="emit('drag', true)" @dragleave.prevent="emit('drag', false)" @drop.prevent="emit('drop', $event)"><div class="drop-icon" :class="{ working: busy === 'inspect' }" aria-hidden="true"><LoaderCircle v-if="busy === 'inspect'" :size="28" class="spinning"/><Upload v-else :size="28" :stroke-width="1.3"/></div><h2>{{ busy === 'inspect' ? t('import.inspecting') : t('ui.drop_chat_records_here') }}</h2><p>{{ t('ui.json_jsonl_txt_markdown_or_html') }}</p><button class="button secondary" :disabled="!!busy || importing" @click="pickFiles"><FolderOpen :size="15"/>{{ t('ui.choose_files') }}</button><small>{{ t('ui.existing_plugins_support_qq_wechat_telegram_and') }}</small></div>
          <div v-for="(file, index) in previewFiles" :key="'preview-' + index" class="file-row import-file"><FileText :size="20"/><div><strong>{{ file.name }}</strong><small>{{ formatSize(file.size) }} {{ t('ui.file_preview_only_not_inspected_or_imported') }}</small></div><button class="icon-button" :aria-label="t('ui.remove_file')" @click="emit('removePreview', index)"><X :size="15"/></button></div>
          <div v-for="(file, index) in files" :key="file.saved_as" class="file-row import-file">
            <FileText :size="20"/>
            <div><strong>{{ file.name }}</strong><small>{{ file.format_label }} · {{ file.total_messages }} {{ t('ui.messages') }} {{ formatSize(file.size) }}</small>
              <small v-if="file.rule_reused">{{ t('import.rule_reused') }}</small>
              <p v-if="file.conversion_stats?.source_warning" class="muted">{{ file.conversion_stats.source_warning }}</p>
              <p v-if="file.conversion_stats?.skipped_records" class="danger-text">{{ t('import.skipped_records').replace('{count}', String(file.conversion_stats.skipped_records)).replace('{total}', String(file.conversion_stats.source_records)) }}</p>
              <p v-if="file.error" class="danger-text">{{ file.error }}</p>
              <button v-if="file.ai_converted || file.error" class="text-button" :disabled="!!busy || importing || completed" :title="t('import.reanalyze_hint')" @click="emit('reanalyze', file)"><RefreshCw :size="12"/>{{ t('import.reanalyze') }}</button>
            </div>
            <button class="icon-button" :aria-label="t('ui.remove_file')" :disabled="!!busy || importing" @click="emit('removeFile', index)"><X :size="15"/></button>
          </div>
          <section v-if="candidates.length && !completed" class="surface identity-selection">
            <h2>{{ t('ui.confirm_both_identities') }}</h2>
            <p v-if="files.some(f => f.ai_converted)" class="muted">{{ t('ui.ai_conversion_ready_choose_who_is_you_and_who_is') }}</p>
            <p class="muted">{{ t('ui.these_files_should_belong_to_the_same') }}</p>
            <div class="identity-groups">
              <fieldset v-for="side in (['self', 'friend'] as const)" :key="side" :disabled="selectionLocked">
                <legend>{{ t(side === 'self' ? 'ui.this_is_me' : 'ui.this_is_my_companion') }}<span>{{ (side === 'self' ? selfUids : friendUids).length }}</span></legend>
                <div class="identity-options">
                  <label v-for="candidate in candidates" :key="candidate.uid" class="identity-option" :class="{ selected: (side === 'self' ? selfUids : friendUids).includes(candidate.uid) }">
                    <input type="checkbox" :value="candidate.uid" :checked="(side === 'self' ? selfUids : friendUids).includes(candidate.uid)" :disabled="(side === 'self' ? friendUids : selfUids).includes(candidate.uid)" @change="selectIdentity(side, candidate.uid, ($event.target as HTMLInputElement).checked)"/>
                    <span><strong>{{ candidate.name }}</strong><small>{{ candidate.uid }}</small><small class="identity-source">{{ accountFiles(candidate.uid) }}</small></span>
                  </label>
                </div>
              </fieldset>
            </div>
            <details v-if="files.some(f => f.identity_previews)" class="identity-samples"><summary>{{ t('import.identity_samples') }}</summary><ul class="identity-previews"><li v-for="candidate in candidates" :key="candidate.uid"><strong>{{ candidate.name }} · {{ candidate.uid }}</strong><p>{{ files.map(file => file.identity_previews?.[candidate.uid]).find(Boolean) || t('import.no_preview') }}</p></li></ul></details>
            <p v-if="selfUids.length && friendUids.length && missingIdentities.length" class="danger-text" role="status">{{ t('import.identities_missing').replace('{files}', missingIdentities.map(file => file.name).join('、')) }}</p>
            <button class="button primary" :disabled="selectionLocked || !ready || !identitySelectionValid" @click="emit('start')">{{ t('ui.confirm_import') }}<ArrowRight :size="15"/></button>
          </section>
          <section v-if="task" class="surface import-result" aria-live="polite">
            <div class="section-heading"><h2>{{ t('ui.import_progress') }}</h2><span class="pill">{{ taskLabel(task.status) }}</span></div>
            <p>{{ task.stage || (['done', 'completed', 'failed', 'cancelled'].includes(task.status) ? taskLabel(task.status) : t('ui.the_original_core_is_processing_this_import')) }}</p>
            <p v-if="task.error" class="danger-text" role="alert">{{ task.error }}</p>
            <template v-if="summary">
              <ul class="import-result-files"><li v-for="name in summary.files" :key="name"><FileText :size="14"/>{{ name }}</li></ul>
              <dl class="import-result-metrics">
                <div><dt>{{ t('import.result_messages') }}</dt><dd>{{ summary.messages }}</dd></div>
                <div><dt>{{ t('import.result_written') }}</dt><dd>{{ summary.written }}</dd></div>
                <div><dt>{{ t('import.result_skipped') }}</dt><dd>{{ summary.skipped }}</dd></div>
                <div><dt>{{ t('import.result_failed') }}</dt><dd :class="{ 'danger-text': summary.failed > 0 }">{{ summary.failed }}</dd></div>
              </dl>
              <p v-if="summary.seconds > 0" class="muted">{{ t('import.result_duration').replace('{seconds}', summary.seconds.toFixed(1)) }}</p>
              <p v-if="summary.smallIndex" class="muted">{{ t('import.small_index_hint') }}</p>
            </template>
            <progress v-if="importing && typeof task.progress === 'number'" :value="task.progress" :max="1"/>
            <button v-if="importing" class="text-button" :disabled="!!busy" @click="emit('cancel')">{{ t('ui.cancel_import') }}</button>
            <div v-if="recovering" class="inline-notice import-core-status" role="status"><LoaderCircle :size="17" class="spinning"/><span>{{ t(recovery === 'restarting' ? 'import.core_restarting' : 'import.core_waiting') }}</span></div>
            <div v-else-if="recovery === 'ready'" class="inline-notice import-core-status"><Check :size="17"/><span>{{ t('import.core_ready') }}</span></div>
            <div v-else-if="recovery === 'failed'" class="inline-notice import-core-status"><Info :size="17"/><span>{{ t('import.core_restart_failed') }}<small class="danger-text">{{ recoveryError }}</small></span><button class="text-button" :disabled="!!busy" @click="emit('retryCore')">{{ t('import.retry_core') }}</button></div>
            <details v-if="task.report"><summary>{{ t('ui.view_import_report') }}</summary><pre>{{ JSON.stringify(task.report, null, 2) }}</pre></details>
          </section>
          <div class="note-line"><ShieldCheck :size="16"/><span>{{ t('ui.original_files_stay_readonly_cloud_embedding_receives') }}</span></div>
  </div>
</template>
