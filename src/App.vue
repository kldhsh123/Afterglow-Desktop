<script setup lang="ts">
import { t, locale, setLocale, supportedLocales } from "./i18n"
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { MessageCircle, SlidersHorizontal, Puzzle, Upload, Download, ArrowRight, ArrowLeft, ChevronRight, ExternalLink, Check, Circle, LoaderCircle, Settings2, Feather, FileText, X, Play, Square, RefreshCw, FolderOpen, ShieldCheck, Info, Clock3, Sparkles, AlertCircle, Send, Plus, Eye, EyeOff, CheckCircle2, QrCode } from 'lucide-vue-next'
import ApiChannelSelect from './components/ApiChannelSelect.vue'
import ApiProtocolSelect from './components/ApiProtocolSelect.vue'
import ModelConcurrency from './components/ModelConcurrency.vue'
import WindowTitlebar from './components/WindowTitlebar.vue'
import DesktopPreferences from './components/DesktopPreferences.vue'
import DebugPreferences from './components/DebugPreferences.vue'
import DebugDrawer from './components/DebugDrawer.vue'
import { appVersion, internalBuild, isInternalBuild } from './domain/build'
import ImportRecords from './components/ImportRecords.vue'
import type { ImportedFile, ImportTask, PreviewFile } from './domain/imports'
import { validImportIdentities } from './domain/imports'
import PresetPicker from './components/PresetPicker.vue'
import ToggleRow from './components/ToggleRow.vue'
import ChatPanel from './components/ChatPanel.vue'
import ExtensionsPanel from './components/ExtensionsPanel.vue'
import AnalysisPanel from './components/AnalysisPanel.vue'
import HistoryImagesPanel from './components/HistoryImagesPanel.vue'
import StickersPanel from './components/StickersPanel.vue'
import DesktopUpdates from './components/DesktopUpdates.vue'
import UpdateNotice from './components/UpdateNotice.vue'
import { applyPreset, channelDefaults, channelKeyUrl, channelsFor, defaultConcurrency, defaultSettings, featureDefinitions, isCustomized, parseSettings, presetName, presets, providerDefinitions, providerIssue, requiredProviders, type AnalysisPreferences, type PresetId, type ProviderId, type Settings } from './domain/settings'
import { chooseFiles, currentInstanceId, isDesktop, openExternal, rpc, type Bootstrap, type ComponentId, type ComponentInfo, type ExtensionInfo, type InstanceInfo, type Result } from './services/desktop'

type Page = 'language' | 'welcome' | 'chat' | 'plugins' | 'settings' | 'components' | 'advanced'
const page = ref<Page>('language')
const settings = ref<Settings>(defaultSettings())
const saved = ref<Settings>(defaultSettings())
const loadedSettings = ref(false)
// Keep the first-run screen hidden until the manager has loaded the instance.
// Otherwise every launch briefly renders the language picker before the saved
// settings can decide whether this is a first run or a resumed setup.
const bootstrapped = ref(false)
const applied = ref<Settings | null>(null)
const components = ref<ComponentInfo[]>([])
const desktopUpdateAvailable = ref(false)
const extensions = ref<ExtensionInfo[]>([])
const credentials = ref<string[]>([])
const busy = ref('')
const toast = ref<{ text: string; error: boolean } | null>(null)
const loadError = ref('')
const dataDir = ref('')
const installationDir = ref('')
const instances = ref<InstanceInfo[]>([])
const showInstanceDialog = ref(false)
const instanceName = ref('')
const instanceNameInput = ref<HTMLInputElement | null>(null)
const keys = reactive<Record<ProviderId, string>>({ deepseek: '', embedding: '', rerank: '', zhipu: '', vision: '', imageImportVision: '', search: '' })
const results = reactive<Partial<Record<ProviderId, { ok: boolean; message: string }>>>({})
const skippedTests = reactive<Partial<Record<ProviderId, boolean>>>({})
const modelOptions = ref<string[]>([])
const channelDrafts = new Map<string, Settings['providers'][ProviderId]>()
function selectChannel(id: ProviderId, channel: string) {
  const current = settings.value.providers[id]
  channelDrafts.set(id + ':' + current.channel, { ...current })
  settings.value.providers[id] = { ...(channelDrafts.get(id + ':' + channel) ?? channelDefaults(id, channel)), verification: 'untested' }
  if (id === 'deepseek') modelOptions.value = []
}
const providerErrors = reactive<Partial<Record<ProviderId, string>>>({})
const recentKeyProfiles = new Map<ProviderId, Settings['providers'][ProviderId]>()
function sameKeyScope(a: Settings['providers'][ProviderId], b: Settings['providers'][ProviderId]) { return a.channel === b.channel && (!['custom', 'tavily', 'searxng'].includes(a.channel) || a.baseUrl.trim().replace(/\/$/, '') === b.baseUrl.trim().replace(/\/$/, '')) }
function hasProviderKey(id: ProviderId) { return !!keys[id].trim() || (credentials.value.includes(id) && sameKeyScope(settings.value.providers[id], recentKeyProfiles.get(id) ?? saved.value.providers[id])) }
function validateServices(ids: ProviderId[], verification = true) {
  let valid = true
  for (const id of ids) { providerErrors[id] = providerIssue(id, settings.value.providers[id], hasProviderKey(id), verification); if (providerErrors[id]) valid = false }
  if (!valid) { notify(t('setup.complete_required'), true); void nextTick(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()) }
  return valid
}
const formProviders = computed(() => providerDefinitions.filter(p => {
  if (p.id === 'imageImportVision') return settings.value.services.imageImportVision && (page.value === 'settings' || step.value === 2)
  if (p.id === 'vision') return settings.value.services.vision === 'separate' && (page.value === 'settings' || step.value === 2)
  if (p.id === 'search') return settings.value.services.webSearch && (page.value === 'settings' || step.value === 2)
  return page.value === 'settings' || step.value === 1
}))
const showOptionalServices = computed(() => page.value === 'settings' || (page.value === 'welcome' && step.value === 2))
const showKeys = ref(false)
const advancedOpen = ref(false)
const hasChanges = computed(() => JSON.stringify(settings.value) !== JSON.stringify(saved.value))
function coreConfiguration(value: Settings) {
  return { debug: value.debug, analysis: value.analysis, features: value.features, services: value.services, selfName: value.selfName, friendName: value.friendName, relationship: value.relationship, providers: Object.fromEntries(providerDefinitions.map(p => { const { verification, ...profile } = value.providers[p.id]; return [p.id, profile] })) }
}
const pendingApply = computed(() => !applied.value || JSON.stringify(coreConfiguration(saved.value)) !== JSON.stringify(coreConfiguration(applied.value)))
const core = computed(() => components.value.find(c => c.id === 'core'))
const step = computed(() => settings.value.onboardingStep)
const steps = computed(() => [locale.value === 'en-US' ? t('ui.configure_reply_processing') : t('ui.choose_a_preset'), t('ui.connect_services'), t('setup.optional_services'), t('ui.import_records'), t('ui.start_chatting')])
const nav = computed(() => [ { id: 'chat' as Page, label: t('ui.chat'), icon: MessageCircle }, { id: 'plugins' as Page, label: t('ui.plugins'), icon: Puzzle } ])
const showServiceForm = computed(() => (page.value === 'welcome' && [1, 2].includes(step.value)) || page.value === 'settings')
const lastLog = ref('')
const logTitle = ref('')
const files = ref<ImportedFile[]>([])
const previewFiles = ref<PreviewFile[]>([])
const selfUids = ref<string[]>([])
const friendUids = ref<string[]>([])
const task = ref<ImportTask | null>(null)
type ImportRecovery = { state: 'restarting' | 'waiting' | 'ready' | 'failed'; error: string; startedAt: number }
const importRecoveries = reactive(new Map<string, ImportRecovery>())
const importRecoveryKey = computed(() => task.value ? currentInstanceId.value + ':' + task.value.task_id : '')
const importRecovery = computed(() => importRecoveries.get(importRecoveryKey.value)?.state ?? 'idle')
const importRecoveryError = computed(() => importRecoveries.get(importRecoveryKey.value)?.error ?? '')
const importRestarting = computed(() => importRecovery.value === 'restarting' || importRecovery.value === 'waiting')
const importNeedsCore = computed(() => ['restarting', 'waiting', 'failed'].includes(importRecovery.value))
const importOpen = ref(false)
const coreReturnTarget = ref<{ page: Page; importOpen: boolean } | null>(null)
const importDialog = ref<HTMLDialogElement | null>(null)
const chatPanel = ref<InstanceType<typeof ChatPanel> | null>(null)
const dragover = ref(false)
const ready = ref(false)
const identityRestartRequired = ref(false)
const coreRestartRequired = computed(() => pendingApply.value || identityRestartRequired.value)
const updateCount = computed(() => components.value.filter(item => item.updateAvailable === true).length + (desktopUpdateAvailable.value ? 1 : 0))
const usable = computed(() => ready.value && !coreRestartRequired.value && !importNeedsCore.value)
const debugOpen = ref(false), debugConversationId = ref<string | undefined>(), debugQuery = ref('')
const debugAvailable = computed(() => usable.value && saved.value.debug.enabled && applied.value?.debug.enabled === true)
function openDebug(context?: { conversationId?: string; query: string }) {
  if (!debugAvailable.value) return
  debugConversationId.value = context?.conversationId
  debugQuery.value = context?.query ?? ''
  debugOpen.value = true
}
watch([currentInstanceId, page, debugAvailable], () => { debugOpen.value = false })
let timer: ReturnType<typeof setTimeout> | undefined
let stopDrop: (() => void) | undefined
let poll: ReturnType<typeof setTimeout> | undefined
let healthTimer: ReturnType<typeof setTimeout> | undefined
let disposed = false
const drafts = new Map<string, { settings: Settings; keys: Record<ProviderId, string>; files: ImportedFile[]; previewFiles: { name: string; size: number }[]; selfUids: string[]; friendUids: string[]; task: typeof task.value }>()
const candidates = computed(() => [...new Map(files.value.flatMap(f => f.candidates).map(c => [c.uid, c])).values()])
const identitySelectionValid = computed(() => validImportIdentities(files.value, selfUids.value, friendUids.value))
watch(candidates, value => {
  const available = new Set(value.map(candidate => candidate.uid))
  selfUids.value = selfUids.value.filter(uid => available.has(uid))
  friendUids.value = friendUids.value.filter(uid => available.has(uid))
})

for (const id of providerDefinitions.map(p => p.id)) {
  watch(() => [settings.value.providers[id].channel, settings.value.providers[id].baseUrl, settings.value.providers[id].model, settings.value.providers[id].protocol || 'chat_completions'], values => {
    const current = saved.value.providers[id]
    if (values.join('\0') !== [current.channel, current.baseUrl, current.model, current.protocol || 'chat_completions'].join('\0')) {
      settings.value.providers[id].verification = 'untested'; skippedTests[id] = false; delete results[id]
    }
  }, { flush: 'sync' })
  watch(() => keys[id], value => { if (value.trim()) { settings.value.providers[id].verification = 'untested'; skippedTests[id] = false; delete results[id] } })
}

function notify(text: string, error = false) { toast.value = { text, error }; clearTimeout(timer); timer = setTimeout(() => toast.value = null, error ? 10000 : 5500) }
async function action<T>(name: string, fn: () => Promise<T>): Promise<T | undefined> { if (busy.value) return; busy.value = name; try { return await fn() } catch (error) { notify(String(error instanceof Error ? error.message : error), true) } finally { busy.value = '' } }
async function refresh() { const state = await rpc<Bootstrap>('bootstrap'); components.value = state.components; extensions.value = state.extensions ?? []; credentials.value = state.credentials; dataDir.value = state.dataDir; instances.value = state.instances; installationDir.value = state.installationDir; applied.value = state.applied ? parseSettings(state.applied) : null; identityRestartRequired.value = state.restartRequired === true; if (!core.value?.running) ready.value = false }
function applyBootstrap(state: Bootstrap) {
  currentInstanceId.value = state.instanceId
  loadedSettings.value = !!state.settings
  const draft = drafts.get(state.instanceId)
  saved.value = state.settings ? parseSettings(state.settings) : defaultSettings()
  settings.value = draft ? parseSettings(draft.settings) : parseSettings(saved.value)
  components.value = state.components
  desktopUpdateAvailable.value = false
  extensions.value = state.extensions ?? []
  credentials.value = state.credentials
  dataDir.value = state.dataDir
  installationDir.value = state.installationDir
  instances.value = state.instances
  applied.value = state.applied ? parseSettings(state.applied) : null
  ready.value = false
  identityRestartRequired.value = state.restartRequired === true
  importOpen.value = false
  coreReturnTarget.value = null
  files.value = draft?.files ?? []
  previewFiles.value = draft?.previewFiles ?? []
  selfUids.value = [...(draft?.selfUids ?? [])]
  friendUids.value = [...(draft?.friendUids ?? [])]
  task.value = draft?.task ?? null
  for (const id of providerDefinitions.map(p => p.id)) { keys[id] = draft?.keys[id] ?? ''; delete results[id]; skippedTests[id] = settings.value.providers[id].verification === 'skipped' }
  modelOptions.value = []
  channelDrafts.clear()
  recentKeyProfiles.clear()
  for (const id of providerDefinitions.map(p => p.id)) delete providerErrors[id]
  lastLog.value = ''
  loadError.value = ''
  // A saved, unfinished setup (including one that has just completed an
  // import) resumes at the wizard. The language picker is only for an
  // instance with no saved settings at all.
  page.value = settings.value.configured ? 'chat' : loadedSettings.value ? 'welcome' : 'language'
  if (task.value && !['done', 'completed', 'failed', 'cancelled'].includes(task.value.status)) void pollImport()
  else if (task.value && ['done', 'completed'].includes(task.value.status) && !importRecoveries.has(importRecoveryKey.value)) void finishImportCore(state.instanceId, task.value.task_id)
}
function keepDraft() {
  if (!currentInstanceId.value) return
  drafts.set(currentInstanceId.value, { settings: parseSettings(settings.value), keys: { ...keys }, files: [...files.value], previewFiles: [...previewFiles.value], selfUids: [...selfUids.value], friendUids: [...friendUids.value], task: task.value })
}
async function switchInstance(id: string) {
  if (id === currentInstanceId.value || busy.value) return
  await action('instance', async () => {
    keepDraft()
    clearTimeout(poll)
    const result = await rpc<Result>('switch_instance', { id })
    applyBootstrap(await rpc<Bootstrap>('bootstrap', { instanceId: id }))
    notify(result.message)
  })
}
async function createInstance() {
  const name = instanceName.value.trim()
  if (!name || busy.value) return
  const created = await action('instance-create', () => rpc<Result & { id: string }>('create_instance', { name }))
  if (!created) return
  showInstanceDialog.value = false
  instanceName.value = ''
  await switchInstance(created.id)
}
async function probeReadiness() {
  const owner = currentInstanceId.value
  if (isDesktop && owner && !disposed) {
    try {
      const status = await rpc<{ components: ComponentInfo[] }>('status', { instanceId: owner })
      if (owner === currentInstanceId.value && !disposed) {
        components.value = status.components
        if (core.value?.running) {
          const recovery = importRecoveries.get(importRecoveryKey.value)
          const health = await rpc<{ restartRequired?: boolean; applied?: Settings | null }>('health', { instanceId: owner })
          if (owner === currentInstanceId.value && !disposed) {
            identityRestartRequired.value = health.restartRequired === true
            if ('applied' in health) applied.value = health.applied ? parseSettings(health.applied) : null
            ready.value = !health.restartRequired
            if (ready.value && recovery?.state === 'waiting' && recovery === importRecoveries.get(importRecoveryKey.value)) importCoreBecameReady(owner)
          }
        } else ready.value = false
      }
    }
    catch { if (owner === currentInstanceId.value) ready.value = false }
    if (owner === currentInstanceId.value) {
      const recovery = importRecoveries.get(importRecoveryKey.value)
      if (recovery?.state === 'waiting' && Date.now() - recovery.startedAt > 120000) {
        recovery.state = 'failed'
        recovery.error = t('import.core_timeout')
      }
    }
  }
  if (!disposed) healthTimer = setTimeout(probeReadiness, ready.value ? 4000 : 2000)
}
function setPanelBusy(panel: string, active: boolean) { if (active && !busy.value) busy.value = panel; else if (!active && busy.value === panel) busy.value = '' }
async function saveAnalysisPreferences(apply = false) {
  await action('analysis-preferences', async () => {
    const analysis: AnalysisPreferences = { ...settings.value.analysis }
    // Merge only these controls; leave unrelated unsaved model edits in the form.
    const latest = await rpc<Bootstrap>('bootstrap')
    const snapshot = parseSettings(latest.settings ?? saved.value)
    snapshot.analysis = analysis
    const result = await rpc<Result>('save_settings', { settings: snapshot })
    saved.value = snapshot
    if (apply) { ready.value = false; await rpc('restart', { id: 'core' }); await refresh() }
    notify(apply ? t('analysis.applying_preferences') : result.message)
  })
}
async function saveDebugPreferences(apply = false) {
  await action('debug-preferences', async () => {
    const debug = { ...settings.value.debug, fullPayloads: settings.value.debug.enabled && settings.value.debug.fullPayloads }
    const latest = await rpc<Bootstrap>('bootstrap')
    const snapshot = parseSettings(latest.settings ?? saved.value)
    snapshot.debug = debug
    await rpc('save_settings', { settings: snapshot })
    saved.value = parseSettings(snapshot)
    settings.value.debug = { ...debug }
    if (apply && core.value?.running) {
      ready.value = false
      await rpc('restart', { id: 'core' })
      await refresh()
      notify(t('debug.applying'))
    } else notify(t(core.value?.running ? 'debug.saved' : 'debug.saved_next_start'))
  })
}
async function checkRepositoryUpdates() {
  await action('check-repositories', async () => {
    let status = await rpc<{ checking: boolean; core?: { failed?: boolean }; desktop?: { failed?: boolean } }>('check_repository_updates')
    while (status.checking && !disposed) {
      await new Promise(resolve => setTimeout(resolve, 700))
      status = await rpc('repository_update_status')
    }
    await refresh()
    notify(t(status.core?.failed || status.desktop?.failed ? 'updates.repository_check_failed' : 'updates.repository_checked'), !!(status.core?.failed || status.desktop?.failed))
  })
}
async function save() { if (settings.value.configured && !validateServices(requiredProviders(settings.value), false)) return; return action('save', async () => { for (const p of providerDefinitions) await saveProviderKey(p.id); const snapshot = parseSettings(JSON.parse(JSON.stringify(settings.value))); const result = await rpc<Result>('save_settings', { settings: snapshot }); saved.value = snapshot; loadedSettings.value = true; notify(result.message); return true }) }
function selectPreset(id: PresetId) { settings.value = applyPreset(settings.value, id); results.rerank = undefined }
async function nextStep() {
  if (step.value === 1 && !validateServices(requiredProviders(settings.value).filter(id => !['vision', 'imageImportVision', 'search'].includes(id)))) return
  if (step.value === 2 && !validateServices(requiredProviders(settings.value))) return
  if (step.value === 3) {
    if (!usable.value) { notify(t('setup.prepare_first'), true); return }
    if (task.value && !['done', 'completed', 'failed', 'cancelled'].includes(task.value.status)) { notify(t('analysis.wait_for_tasks'), true); return }
    if (files.value.length && !['done', 'completed'].includes(task.value?.status ?? '')) { notify(t('setup.finish_import'), true); return }
  }
  const previous = step.value
  settings.value.onboardingStep = Math.min(4, previous + 1)
  if (!await save()) settings.value.onboardingStep = previous
}
async function previousStep() { if (step.value > 0) settings.value.onboardingStep--; await save() }
async function saveProviderKey(id: ProviderId) { if (keys[id].trim()) {
  const profile = { ...settings.value.providers[id] }
  await rpc('set_secret', { name: id, value: keys[id], profile })
  recentKeyProfiles.set(id, profile)
  if (!credentials.value.includes(id)) credentials.value.push(id)
  keys[id] = ''
} }
async function testProvider(id: ProviderId) { if (!(id === 'deepseek' && settings.value.providers[id].channel === 'deepseek' && !settings.value.providers[id].model.trim()) && !validateServices([id], false)) return; await action('provider-' + id, async () => { await saveProviderKey(id); skippedTests[id] = false; settings.value.providers[id].verification = 'untested'; try { const result = await rpc<Result>('test_provider', { provider: id, channel: settings.value.providers[id].channel, baseUrl: settings.value.providers[id].baseUrl, model: settings.value.providers[id].model, protocol: settings.value.providers[id].protocol || 'chat_completions' }); results[id] = result; if (result.ok) settings.value.providers[id].verification = 'verified'; if (result.models && id === 'deepseek') modelOptions.value = result.models; notify(result.message) } catch (error) { results[id] = { ok: false, message: String(error instanceof Error ? error.message : error) } } }) }
async function skipProviderTest(id: ProviderId) { if (!validateServices([id], false)) return; await action('provider-skip-' + id, async () => { await saveProviderKey(id); settings.value.providers[id].verification = 'skipped'; const snapshot = parseSettings(JSON.parse(JSON.stringify(settings.value))); await rpc('save_settings', { settings: snapshot }); saved.value = snapshot; skippedTests[id] = true; results[id] = { ok: true, message: t('ui.configuration_saved_without_verification') }; notify(t('ui.test_skipped_configuration_saved')) }) }
async function visit(url: string) { try { await openExternal(url) } catch (e) { notify(String(e), true) } }
async function componentAction(id: ComponentId, operation: string, path?: string) { await action(operation + '-' + id, async () => { const method = operation === 'install' && core.value?.version ? 'update_core' : operation; const result = await rpc<Result>(method, { id, ...(path ? { path } : {}) }); notify(result.message); if (['stop', 'restart', 'update_core'].includes(method) && id === 'core') ready.value = false; await refresh() }) }
async function prepareCore() {
  if (importRecovery.value === 'restarting' || importRecovery.value === 'waiting') return
  if (!validateServices(requiredProviders(settings.value), false)) return
  await action('prepare-core', async () => {
    const snapshot = parseSettings(JSON.parse(JSON.stringify(settings.value)))
    for (const provider of providerDefinitions) await saveProviderKey(provider.id)
    await rpc('save_settings', { settings: snapshot })
    saved.value = snapshot
    loadedSettings.value = true
    for (const provider of providerDefinitions) await saveProviderKey(provider.id)
    if (!core.value?.version) { await rpc('install', { id: 'core' }); await refresh() }
    if (!core.value?.running) { await rpc('start', { id: 'core' }); await refresh() }
    else if (coreRestartRequired.value) { await rpc('restart', { id: 'core' }); await refresh() }
    try { const state = await rpc<{ restartRequired?: boolean }>('health'); identityRestartRequired.value = state.restartRequired === true; ready.value = !state.restartRequired } catch { ready.value = false }
    notify(t(ready.value ? 'ui.the_core_is_ready' : 'setup.core_starting'))
  })
}
async function importPackage(id: ComponentId) { try { const paths = await chooseFiles(true); if (paths[0]) await componentAction(id, 'install', paths[0]) } catch (e) { notify(String(e), true) } }
async function checkCore() { await action('health', async () => { const health = await rpc<{ restartRequired?: boolean }>('health'); await refresh(); identityRestartRequired.value = health.restartRequired === true; ready.value = !health.restartRequired; notify(t(health.restartRequired ? 'analysis.restart_identity' : 'ui.the_core_is_ready')) }) }
async function viewLog(id: ComponentId) { await action('logs', async () => { const result = await rpc<{ text: string }>('logs', { id }); lastLog.value = result.text; logTitle.value = components.value.find(c => c.id === id)?.name ?? id }) }
function manageCore() {
  coreReturnTarget.value = { page: page.value, importOpen: importOpen.value }
  importOpen.value = false
  page.value = 'components'
}
async function returnFromCore() {
  const target = coreReturnTarget.value ?? { page: 'welcome' as Page, importOpen: false }
  coreReturnTarget.value = null
  page.value = target.page
  await nextTick()
  importOpen.value = target.importOpen
}
async function receivePaths(paths: string[]) { if (!paths.length || busy.value || (task.value && !['done','completed','failed','cancelled'].includes(task.value.status))) return; if (page.value !== 'welcome' || step.value !== 3) importOpen.value = true; if (task.value) task.value = null; await action('inspect', async () => { const result = await rpc<{ uploaded: ImportedFile[] }>('inspect_files', { paths }); files.value.push(...result.uploaded); notify(t('ui.the_original_core_has_inspected_the_files')) }) }
async function pickFiles() { try { await receivePaths(await chooseFiles()) } catch (e) { notify(String(e), true) } }
async function reanalyzeFile(file: ImportedFile) {
  await action('inspect', async () => {
    const result = await rpc<{ uploaded: ImportedFile[] }>('reanalyze_import', { saved_as: file.saved_as })
    const index = files.value.findIndex(item => item.saved_as === file.saved_as)
    if (index >= 0 && result.uploaded.length) files.value.splice(index, 1, ...result.uploaded)
  })
}
async function dropFiles(event: DragEvent) { dragover.value = false; const dropped = Array.from(event.dataTransfer?.files ?? []); if (!isDesktop) { previewFiles.value.push(...dropped.map(f => ({ name: f.name, size: f.size }))); notify(t('ui.file_details_loaded_format_detection_and_import')); return } }
async function startImport() { if (!identitySelectionValid.value || !usable.value) return; await action('import', async () => { const result = await rpc<{ task_id: string; status: string }>('start_import', { files: files.value.map(f => f.saved_as), fileNames: files.value.map(f => f.name), selfUids: [...selfUids.value], friendUids: [...friendUids.value] }); task.value = result; void pollImport() }) }
function importCoreBecameReady(owner: string) {
  if (owner !== currentInstanceId.value) return
  const recovery = importRecoveries.get(importRecoveryKey.value)
  if (recovery?.state === 'waiting') {
    recovery.state = 'ready'
    notify(t('import.core_ready'))
  }
}
async function finishImportCore(owner: string, taskId: string, retry = false) {
  const key = owner + ':' + taskId
  if (disposed || (!retry && importRecoveries.has(key))) return
  importRecoveries.set(key, { state: 'restarting', error: '', startedAt: Date.now() })
  if (owner === currentInstanceId.value) ready.value = false
  try {
    // Retain the finished task and report in this window. The old core's task
    // endpoint no longer exists after restart, so never poll it again.
    await rpc('restart', { id: 'core', instanceId: owner })
    importRecoveries.set(key, { state: 'waiting', error: '', startedAt: Date.now() })
    if (owner !== currentInstanceId.value || disposed) return
    const state = await rpc<Bootstrap>('bootstrap', { instanceId: owner })
    if (owner !== currentInstanceId.value || disposed) return
    components.value = state.components
    applied.value = state.applied ? parseSettings(state.applied) : null
    identityRestartRequired.value = state.restartRequired === true
    // The regular health probe completes the transition when /readyz responds.
  } catch (error) {
    const message = String(error instanceof Error ? error.message : error)
    importRecoveries.set(key, { state: 'failed', error: message, startedAt: Date.now() })
    if (owner === currentInstanceId.value && !disposed) notify(t('import.core_restart_failed') + ' ' + message, true)
  }
}
function retryImportCore() { if (task.value && importRecovery.value === 'failed') void finishImportCore(currentInstanceId.value, task.value.task_id, true) }
async function pollImport() {
  if (!task.value || disposed) return
  const owner = currentInstanceId.value, taskId = task.value.task_id
  try {
    const state = await rpc<ImportTask>('import_status', { id: taskId, instanceId: owner })
    if (owner !== currentInstanceId.value || disposed || task.value?.task_id !== taskId) return
    task.value = state
    if (!['done', 'completed', 'failed', 'cancelled'].includes(state.status)) poll = setTimeout(pollImport, 1500)
    else if (state.status === 'done' || state.status === 'completed') await finishImportCore(owner, taskId)
  } catch (error) { if (owner === currentInstanceId.value && !disposed) notify(String(error), true) }
}
async function cancelImport() { if (!task.value) return; await action('cancel-import', async () => { await rpc('cancel_import', { id: task.value!.task_id }); notify(t('ui.import_cancellation_requested')) }) }
function addPreviewFiles(added: PreviewFile[]) { previewFiles.value.push(...added); if (added.length) notify(t('ui.file_details_loaded_format_detection_and_import')) }
function closeImportBackdrop(event: MouseEvent) { const dialog = importDialog.value; if (event.target !== dialog || !dialog) return; const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) importOpen.value = false }
async function finish() {
  if (!validateServices(requiredProviders(settings.value))) { settings.value.onboardingStep = 1; return }
  if (!usable.value) { notify(t('setup.prepare_first'), true); return }
  settings.value.configured = true
  if (await save()) page.value = 'chat'
  else settings.value.configured = false
}
function continueFromLanguage() { if (!loadedSettings.value) settings.value = defaultSettings(locale.value); page.value = 'welcome' }
onMounted(async () => { try { applyBootstrap(await rpc<Bootstrap>('bootstrap')) } catch (e) { loadError.value = String(e); notify(String(e), true) } finally { bootstrapped.value = true } if (isDesktop && settings.value.configured) await prepareCore(); void probeReadiness(); if (isDesktop) { try { const { getCurrentWebview } = await import('@tauri-apps/api/webview'); stopDrop = await getCurrentWebview().onDragDropEvent(event => {
  if (event.payload.type === 'drop') {
    const paths = event.payload.paths
    if (page.value === 'chat' && !importOpen.value && paths.length && paths.every(path => /\.(jpe?g|png|gif|webp)$/i.test(path))) void chatPanel.value?.attachPaths(paths)
    else void receivePaths(paths)
  }
  dragover.value = event.payload.type === 'over'
}) } catch (e) { notify(String(e), true) } } })
onUnmounted(() => { disposed = true; clearTimeout(timer); clearTimeout(poll); clearTimeout(healthTimer); stopDrop?.(); for (const draft of drafts.values()) Object.keys(draft.keys).forEach(id => draft.keys[id as ProviderId] = '') })
watch(page, (value, previous) => { advancedOpen.value = false; importOpen.value = false; if (previous === 'components' && value !== 'components') coreReturnTarget.value = null })
watch(importOpen, async value => { await nextTick(); const dialog = importDialog.value; if (value && !dialog?.open) dialog?.showModal(); else if (!value && dialog?.open) dialog.close() })
watch(showInstanceDialog, async value => { if (value) { await nextTick(); instanceNameInput.value?.focus() } })
</script>

<template>
  <WindowTitlebar @error="notify($event, true)"/>
  <UpdateNotice :key="currentInstanceId" :visible="page !== 'language'" @open="page = 'components'"/>
  <div v-if="!bootstrapped" class="language-screen app-loading-screen" aria-busy="true">
    <div class="language-card"><img src="/afterglow-icon.svg" alt="" class="language-mark" /><span class="eyebrow">Afterglow</span><LoaderCircle :size="22" class="spinning" /></div>
  </div>
  <div v-else-if="page === 'language'" class="language-screen">
    <div class="language-card">
      <img src="/afterglow-icon.svg" alt="" class="language-mark" />
      <span class="eyebrow">{{ t('language.first_run') }}</span>
      <h1>{{ t('language.title') }}</h1>
      <p class="language-intro">{{ t('language.description') }}</p>
      <div class="language-options" role="group" :aria-label="t('common.language')">
        <button v-for="item in supportedLocales" :key="item.id" class="language-option" :class="{ selected: locale === item.id }" :aria-pressed="locale === item.id" @click="setLocale(item.id)">
          <span class="language-option-copy"><strong>{{ item.name }}</strong><small>{{ item.id }}</small></span>
          <Check v-if="locale === item.id" :size="18" />
          <span v-else class="language-radio" aria-hidden="true" />
        </button>
      </div>
      <button class="button primary language-continue" @click="continueFromLanguage">{{ t('language.continue') }}<ArrowRight :size="16" /></button>
      <small class="language-footnote">{{ t('language.change_later') }}</small>
    </div>
  </div>
  <div v-else class="app-shell">
    <aside class="sidebar">
      <button class="brand" @click="page = settings.configured ? 'chat' : 'welcome'"><img src="/afterglow-icon.svg" alt=""/><span>Afterglow<small>{{ t('ui.afterglow') }}</small></span></button>
      <div class="workspace-label">{{ t('ui.your_companion_space') }}</div>
      <nav :aria-label="t('ui.main_navigation')"><button v-for="item in nav" :key="item.id" :class="{ active: page === item.id }" :disabled="!settings.configured" @click="page = item.id"><component :is="item.icon" :size="18" :stroke-width="1.6"/><span>{{ item.label }}</span><ChevronRight v-if="page === item.id" :size="14"/></button></nav>
      <div class="sidebar-note"><Feather :size="24" :stroke-width="1"/><p>{{ t('ui.keep_the_words_that_warmed_you') }}<br/>{{ t('ui.and_carry_them_into_tomorrow') }}</p></div>
      <div class="sidebar-bottom"><button :class="{ active: page === 'components' }" :disabled="!settings.configured" @click="page = 'components'"><Download :size="17"/>{{ t('ui.components_updates') }}<span v-if="updateCount" class="count">{{ updateCount }}</span></button><button :class="{ active: page === 'settings' }" :disabled="!settings.configured" @click="page = 'settings'"><SlidersHorizontal :size="17"/>{{ t('ui.settings') }}</button><button :class="{ active: page === 'advanced' }" :disabled="!settings.configured" @click="page = 'advanced'"><Settings2 :size="17"/>{{ t('ui.advanced_analysis') }}</button><div class="local-state"><span class="status-dot" :class="{ online: usable }"/>{{ usable ? t('ui.core_ready') : isDesktop ? t('ui.desktop_manager') : t('ui.interface_preview') }}<small :title="appVersion">{{ isInternalBuild ? t('build.internal', { build: internalBuild }) : 'v' + appVersion }}</small></div></div>
    </aside>

    <main>
      <header class="topbar"><div class="breadcrumb">{{ t('ui.my_afterglow') }}<span>/</span>{{ { welcome: t('ui.get_started'), chat: t('ui.chat'), plugins: t('ui.plugins'), settings: t('ui.settings'), components: t('ui.components_updates'), advanced: t('ui.advanced_analysis') }[page] }}</div><div class="topbar-actions"><div class="instance-control"><select :value="currentInstanceId" :aria-label="t('instances.select')" :disabled="!!busy || !instances.length" @change="switchInstance(($event.target as HTMLSelectElement).value)"><option v-for="instance in instances" :key="instance.id" :value="instance.id">{{ instance.id === 'default' ? t('instances.default') : instance.name }}{{ instance.running ? ' · ' + t('instances.running') : '' }}</option></select><button class="icon-button" :aria-label="t('instances.create')" :title="t('instances.create')" :disabled="!!busy" @click="showInstanceDialog = true"><Plus :size="16"/></button></div><select class="language-select" :value="locale" :aria-label="t('common.language')" @change="setLocale(($event.target as HTMLSelectElement).value)"><option v-for="language in supportedLocales" :key="language.id" :value="language.id">{{ language.name }}</option></select><button class="top-status" :disabled="!settings.configured" @click="page = 'components'"><span class="status-dot" :class="{ online: usable }"/>{{ usable ? t('ui.core_running') : core?.version ? t('ui.core_installed') : t('ui.core_not_installed') }}</button></div></header>
      <div v-if="!isDesktop" class="preview-banner"><Info :size="14"/>{{ t('ui.browser_preview_try_settings_here_running_components') }}</div>
      <div v-if="loadError" class="error-banner"><AlertCircle :size="17"/>{{ t('ui.manager_connection_failed') }}{{ loadError }}</div>

      <div class="content" :class="{ 'chat-content': page === 'chat' }">
        <Transition name="flow" mode="out-in"><div v-if="page !== 'chat'" :key="page + '-' + (page === 'welcome' ? step : '')" class="page-flow">
        <template v-if="page === 'welcome'">
          <div class="page-intro"><span class="eyebrow"><Feather :size="14"/> {{ t('ui.a_little_warmth_continued') }}</span><h1>{{ [t('ui.let_a_familiar_voice_return'), t('ui.connect_your_services'), t('setup.optional_services'), t('ui.start_with_your_conversations'), t('ui.ready_to_talk_again')][step] }}</h1><p>{{ [t('ui.choose_a_preset_and_follow_a_few'), t('setup.services_hint'), t('setup.optional_hint'), t('ui.existing_import_plugins_are_tried_first_your'), t('ui.review_your_choices_you_can_change_them')][step] }}</p></div>
          <ol class="stepper"><li v-for="(label, index) in steps" :key="label" :class="{ current: step === index, complete: step > index }"><span><Check v-if="step > index" :size="13"/><template v-else>{{ index + 1 }}</template></span>{{ label }}<i v-if="index < 4"/></li></ol>
          <section v-if="step === 0" class="setup-section"><div class="section-heading"><div><h2>{{ locale === 'en-US' ? t('ui.configure_reply_processing') : t('ui.choose_a_reply_style') }}</h2><p>{{ locale === 'en-US' ? t('ui.configure_each_model_channel_and_processing_option_manually') : t('ui.quick_is_recommended_all_three_presets_include') }}</p></div><span class="quiet-label">{{ t('ui.change_this_anytime') }}</span></div><PresetPicker v-if="locale !== 'en-US'" :model-value="settings.preset" @update:model-value="selectPreset"/><template v-else><ToggleRow v-for="f in featureDefinitions" :key="f.id" v-model="settings.features[f.id]" :label="f.label" :description="f.description" :cost="f.cost"/><ToggleRow v-model="settings.humanDelay" :label="t('ui.simulated_typing_delay')" :description="t('ui.add_a_brief_typing_delay_before_showing')" :cost="t('ui.adds_waiting_without_improving_model_ability_adapter')"/></template><div class="note-line"><Clock3 :size="16"/><span>{{ t('ui.response_time_depends_on_the_model_network') }}</span></div><details v-if="locale !== 'en-US'" class="feature-details"><summary>{{ t('ui.how_do_these_presets_differ') }}<ChevronRight :size="15"/></summary><table><thead><tr><th>{{ t('ui.processing_step') }}</th><th>{{ t('ui.quick') }}</th><th>{{ t('ui.balanced') }}</th><th>{{ t('ui.careful') }}</th></tr></thead><tbody><tr><td>{{ t('ui.basic_memory_retrieval') }}</td><td>{{ t('ui.included') }}</td><td>{{ t('ui.included') }}</td><td>{{ t('ui.included') }}</td></tr><tr v-for="f in featureDefinitions" :key="f.id"><td>{{ f.label }}</td><td v-for="p in presets" :key="p.id">{{ p.features[f.id] ? t('ui.on') : t('ui.off') }}</td></tr></tbody></table></details></section>
          <section v-if="step === 4" class="surface summary-surface"><Feather :size="30" :stroke-width="1.2"/><h2>{{ t('ui.start_at_your_own_pace') }}</h2><dl><div v-if="locale !== 'en-US'"><dt>{{ t('ui.reply_preset') }}</dt><dd>{{ presetName(settings) }}</dd></div><div><dt>{{ t('ui.extra_memory_reranking') }}</dt><dd>{{ settings.features.rerank ? t('ui.on') : t('ui.off') }}</dd></div><div><dt>{{ t('ui.simulated_typing_delay') }}</dt><dd>{{ settings.humanDelay ? t('ui.on') : t('ui.off') }}</dd></div><div><dt>{{ t('ui.channels') }}</dt><dd>{{ t('ui.desktop_add_qq_and_wechat_later') }}</dd></div><div><dt>{{ t('ui.core_status') }}</dt><dd>{{ usable ? t('ui.ready') : t('ui.not_ready_yet_you_can_save_your') }}</dd></div></dl><p class="muted">{{ t('ui.the_wizard_saves_your_progress_saving_settings') }}</p></section>
        </template>

        <template v-if="page === 'settings'">
          <DesktopPreferences @error="notify($event, true)"/>
          <DebugPreferences :preferences="settings.debug" :pending-apply="JSON.stringify(saved.debug) !== JSON.stringify(applied?.debug)" :changed="JSON.stringify(settings.debug) !== JSON.stringify(saved.debug)" :running="!!core?.running" :available="debugAvailable" :busy="!!busy" @update:preferences="settings.debug = $event" @save="saveDebugPreferences()" @apply="saveDebugPreferences(true)" @open="openDebug()"/>
          <div class="page-intro"><span class="eyebrow">{{ t('ui.your_preferences') }}</span><h1>{{ t('ui.make_it_feel_familiar') }}</h1><p>{{ t('ui.choose_a_preset_then_adjust_the_details') }}</p></div>
          <section class="setup-section"><div class="section-heading"><div><h2>{{ t('ui.reply_style') }}</h2><p>{{ locale === 'en-US' ? t('ui.configure_each_model_channel_and_processing_option_manually') : t('ui.quick_is_recommended_balanced_also_enables_memory') }}</p></div><span v-if="locale !== 'en-US'" class="pill">{{ presetName(settings) }}</span></div><template v-if="locale !== 'en-US'"><PresetPicker :model-value="settings.preset" @update:model-value="selectPreset"/></template><template v-else><ToggleRow v-for="f in featureDefinitions" :key="f.id" v-model="settings.features[f.id]" :label="f.label" :description="f.description" :cost="f.cost"/><ToggleRow v-model="settings.humanDelay" :label="t('ui.simulated_typing_delay')" :description="t('ui.add_a_brief_typing_delay_before_showing')" :cost="t('ui.adds_waiting_without_improving_model_ability_adapter')"/></template></section>
          <section v-if="locale !== 'en-US'" class="surface"><div class="section-heading"><div><h2>{{ t('ui.common_features') }}</h2><p>{{ t('ui.changing_individual_switches_marks_the_preset_as') }}</p></div><button class="text-button" @click="selectPreset(settings.preset)">{{ t('ui.reset_preset_switches') }}</button></div><ToggleRow v-for="f in featureDefinitions" :key="f.id" v-model="settings.features[f.id]" :label="f.label" :description="f.description" :cost="f.cost"/><ToggleRow v-model="settings.humanDelay" :label="t('ui.simulated_typing_delay')" :description="t('ui.add_a_brief_typing_delay_before_showing')" :cost="t('ui.adds_waiting_without_improving_model_ability_adapter')"/></section>
          <section class="surface"><div class="section-heading"><div><h2>{{ t('ui.you_and_your_companion') }}</h2><p>{{ t('ui.you_can_edit_names_here_confirm_account') }}</p></div><Feather :size="21"/></div><div class="form-grid"><label>{{ t('ui.your_name') }}<input v-model="settings.selfName" maxlength="80" :placeholder="t('ui.what_should_we_call_you')"/></label><label>{{ t('ui.their_name') }}<input v-model="settings.friendName" maxlength="80" :placeholder="t('ui.a_familiar_name')"/></label><label>{{ t('ui.your_relationship') }}<select v-model="settings.relationship"><option value="friend">{{ t('ui.friend') }}</option><option value="lover">{{ t('ui.partner') }}</option><option value="family">{{ t('ui.family') }}</option><option value="colleague">{{ t('ui.colleague') }}</option></select></label></div></section>
        </template>

        <section v-if="page === 'welcome' && step >= 3" class="core-setup" :aria-label="t('setup.core_title')">
          <div class="core-setup-symbol"><CheckCircle2 v-if="usable" :size="23"/><LoaderCircle v-else-if="busy === 'prepare-core' || importRestarting" :size="23" class="spinning"/><Feather v-else :size="23"/></div>
          <div class="core-setup-copy"><h2>{{ importRestarting ? t('setup.core_waiting') : usable ? t('setup.core_ready') : core?.running && !coreRestartRequired ? t('setup.core_waiting') : t('setup.core_title') }}</h2><p>{{ importRestarting ? t(importRecovery === 'restarting' ? 'import.core_restarting' : 'import.core_waiting') : usable ? t('setup.core_ready_hint') : core?.running && !coreRestartRequired ? t('setup.core_waiting_hint') : t('setup.core_hint') }}</p></div>
          <button v-if="!usable && !importRestarting && (!core?.running || coreRestartRequired)" class="button primary" :disabled="!!busy || !isDesktop" @click="core?.running && !coreRestartRequired ? checkCore() : prepareCore()"><LoaderCircle v-if="busy === 'prepare-core'" :size="14" class="spinning"/><Play v-else :size="14"/>{{ busy === 'prepare-core' ? t('setup.core_working') : core?.running ? t(coreRestartRequired ? 'analysis.restart_apply' : 'ui.check_readiness') : t('setup.core_prepare') }}</button>
          <span v-else-if="usable" class="pill success">{{ t('ui.ready') }}</span><span v-else class="pill"><LoaderCircle :size="14" class="spinning"/>{{ t('setup.core_waiting') }}</span>
        </section>
        <section v-if="showOptionalServices" class="surface optional-services">
          <div class="section-heading"><div><h2>{{ t('setup.optional_services') }}</h2><p>{{ t('setup.optional_hint') }}</p></div><Sparkles :size="22"/></div>
          <fieldset class="vision-options"><legend>{{ t('services.vision') }}</legend><p>{{ t('services.vision_modes_hint') }}</p><div class="vision-choice-grid"><label v-for="mode in (['off', 'main', 'separate'] as const)" :key="mode" class="vision-choice" :class="{ selected: settings.services.vision === mode }"><input v-model="settings.services.vision" type="radio" name="vision-mode" :value="mode"/><span><strong>{{ t(mode === 'off' ? 'services.vision_off' : mode === 'main' ? 'services.vision_main' : 'services.vision_separate') }}</strong><small>{{ t(mode === 'off' ? 'services.vision_off_hint' : mode === 'main' ? 'services.vision_main_hint' : 'services.vision_separate_hint') }}</small></span></label></div></fieldset>
          <ToggleRow v-model="settings.services.imageImportVision" :label="t('services.image_import_vision')" :description="t('services.image_import_vision_hint')" :cost="t('services.image_import_vision_cost')"/>
          <ToggleRow v-model="settings.services.webSearch" :label="t('services.search')" :description="t('services.search_description')" :cost="t('services.search_cost')"/>
          <ToggleRow v-model="settings.services.webFetch" :label="t('services.web_fetch')" :description="t('services.web_fetch_description')" :cost="t('services.web_fetch_cost')"/>
          <p class="note-line"><ShieldCheck :size="16"/><span>{{ t('services.optional_privacy') }}</span></p>
        </section>
        <section v-if="showServiceForm && formProviders.length" class="service-section"><div class="section-heading"><div><h2>{{ t(page === 'welcome' && step === 2 ? 'setup.optional_connections' : 'ui.model_services') }}</h2><p>{{ t('setup.services_hint') }}</p></div><button class="icon-button" :aria-label="showKeys ? t('ui.hide_keys') : t('ui.show_keys')" @click="showKeys = !showKeys"><EyeOff v-if="showKeys" :size="18"/><Eye v-else :size="18"/></button></div><article v-for="provider in formProviders" :key="provider.id" :id="'provider-' + provider.id" class="provider-row" :class="{ 'provider-invalid': providerErrors[provider.id] }"><div class="provider-symbol" :class="settings.providers[provider.id].channel"><component :is="provider.id === 'deepseek' ? MessageCircle : provider.id === 'zhipu' ? Sparkles : provider.id === 'embedding' ? FileText : SlidersHorizontal" :size="20" :stroke-width="1.5"/></div><div class="provider-body"><div class="provider-heading"><h3>{{ provider.name }}<small class="provider-requirement">{{ t(requiredProviders(settings).includes(provider.id) ? 'setup.required' : 'setup.not_needed') }}</small><span>{{ provider.role }}</span></h3><button v-if="channelKeyUrl(provider.id, settings.providers[provider.id].channel) && !(provider.id === 'search' && settings.providers[provider.id].channel === 'searxng')" class="text-button" @click="visit(channelKeyUrl(provider.id, settings.providers[provider.id].channel))">{{ t(provider.id === 'embedding' ? 'services.embedding_key' : provider.id === 'rerank' ? 'services.rerank_key' : 'ui.get_a_key') }}<ExternalLink :size="12"/></button></div><p>{{ provider.description }}</p><div class="model-select"><label :for="'channel-' + provider.id">{{ t('ui.api_channel') }}</label><ApiChannelSelect :id="'channel-' + provider.id" :model-value="settings.providers[provider.id].channel" :channels="channelsFor(provider.id)" @update:model-value="selectChannel(provider.id, $event)" :label="provider.name + ' · ' + t('ui.api_channel')"/></div>
<ApiProtocolSelect v-if="['deepseek', 'zhipu', 'vision', 'imageImportVision'].includes(provider.id)" v-model="settings.providers[provider.id].protocol" :label="provider.name"/>

<div v-if="settings.providers[provider.id].channel === 'custom' || provider.id === 'search'" class="custom-provider-fields"><label>{{ t('ui.api_base_url') }}<input v-model="settings.providers[provider.id].baseUrl" type="url" placeholder="https://api.example.com/v1" :disabled="!isDesktop"/></label><label v-if="provider.id !== 'search'">{{ t('ui.model_name') }}<input v-model="settings.providers[provider.id].model" :placeholder="t('ui.enter_model_name')" :disabled="!isDesktop"/></label></div><label v-else class="model-select">{{ t('ui.model_name') }}<input v-model="settings.providers[provider.id].model" :placeholder="t('ui.choose_a_model_available_to_your_account')" :disabled="!isDesktop"/><small v-if="provider.id === 'deepseek' && modelOptions.length">{{ t('ui.available_models') }}: {{ modelOptions.join(', ') }}</small></label><p v-if="settings.providers[provider.id].channel === 'custom'" class="channel-key-hint">{{ t('services.custom_key_hint') }}</p><div class="key-input"><input v-model="keys[provider.id]" :type="showKeys ? 'text' : 'password'" autocomplete="off" :aria-label="provider.name + t('ui.api_key')" :aria-invalid="!!providerErrors[provider.id]" :aria-describedby="providerErrors[provider.id] ? 'provider-error-' + provider.id : undefined" :placeholder="hasProviderKey(provider.id) ? t('ui.encrypted_key_saved_enter_a_replacement') : t('ui.paste_your_service_key')" :disabled="!isDesktop"/><button class="button secondary" :disabled="!!busy || !isDesktop" @click="testProvider(provider.id)"><LoaderCircle v-if="busy === 'provider-' + provider.id" :size="14" class="spinning"/><CheckCircle2 v-else :size="14"/>{{ t('ui.save_test') }}</button></div><p v-if="providerErrors[provider.id]" :id="'provider-error-' + provider.id" class="field-error" role="alert">{{ providerErrors[provider.id] }}</p><small v-if="provider.id === 'search' && settings.providers.search.channel === 'searxng'" class="muted">{{ t('services.searxng_key_optional') }}</small><div v-if="results[provider.id] || settings.providers[provider.id].verification === 'skipped'" class="test-result"><p>{{ results[provider.id]?.message }}</p><button v-if="!results[provider.id]?.ok" class="text-button" :disabled="!!busy || !isDesktop" @click="skipProviderTest(provider.id)">{{ t('ui.confirm_settings_skip_test') }}</button><span v-if="skippedTests[provider.id] || settings.providers[provider.id].verification === 'skipped'" class="pill">{{ t('ui.unverified') }}</span></div>
<ModelConcurrency v-if="provider.id !== 'search'" :id="'concurrency-' + provider.id" v-model="settings.providers[provider.id].concurrency" :default-value="defaultConcurrency(settings.providers[provider.id].channel, settings.providers[provider.id].model)" :hint="t(provider.id === 'embedding' ? 'concurrency.embedding' : provider.id === 'zhipu' ? 'concurrency.small' : provider.id === 'rerank' ? 'concurrency.rerank' : ['vision', 'imageImportVision'].includes(provider.id) ? 'concurrency.vision' : 'concurrency.main')" :disabled="!!busy || !isDesktop"/>
</div></article><div class="note-line"><ShieldCheck :size="16"/><span>{{ isDesktop ? t('ui.windows_encrypts_your_keys_they_stay_out') : t('ui.browser_preview_does_not_collect_or_save') }}</span></div></section>

        <ImportRecords v-if="page === 'welcome' && step === 3" :files="files" :preview-files="previewFiles" :candidates="candidates" v-model:self-uids="selfUids" v-model:friend-uids="friendUids" :task="task" :dragover="dragover" :busy="busy" :ready="usable" :identity-selection-valid="identitySelectionValid" :recovery="importRecovery" :recovery-error="importRecoveryError" @retry-core="retryImportCore" @pick="pickFiles" @preview="addPreviewFiles" @drop="dropFiles" @drag="dragover = $event" @remove-file="files.splice($event, 1)" @remove-preview="previewFiles.splice($event, 1)" @reanalyze="reanalyzeFile" @start="startImport" @cancel="cancelImport" @manage-core="manageCore"/>


        <ExtensionsPanel v-if="page === 'plugins' && currentInstanceId" :key="currentInstanceId" :instance-id="currentInstanceId" :ready="usable" @error="notify($event, true)" @busy="busy = $event ? 'extension' : ''"/>

        <template v-if="page === 'components'">
          <button v-if="coreReturnTarget || !settings.configured" class="text-button core-return" @click="returnFromCore"><ArrowLeft :size="15"/>{{ t(coreReturnTarget?.page === 'welcome' || !settings.configured ? 'setup.return_to_setup' : 'import.return_to_import') }}</button>
          <div class="page-intro"><span class="eyebrow">{{ t('ui.original_projects_independent_updates') }}</span><h1>{{ t('ui.look_after_every_component') }}</h1><p>{{ t('ui.manage_the_original_core_and_adapters_update') }}</p></div>
          <DesktopUpdates :busy="!!busy" @busy="busy = $event ? 'desktop-update' : ''" @refreshed="refresh" @notice="notify" @availability="desktopUpdateAvailable = $event"/>
          <div class="component-actions"><button class="button secondary" :disabled="!!busy || !isDesktop" @click="checkRepositoryUpdates"><RefreshCw :size="14"/>{{ t('updates.check') }}</button></div><div class="component-list"><article v-for="item in components" :key="item.id" class="component-card"><div class="component-icon" :class="item.id"><Feather :size="25"/></div><div class="component-body"><div class="component-title"><h2>{{ t('ui.afterglow_core') }}</h2><span class="pill" :class="{ success: item.running }">{{ item.running ? t(usable ? 'ui.core_ready' : 'ui.process_running') : item.version ? t('ui.installed') + item.version : t('ui.not_installed') }}</span></div><p>{{ t('ui.keeps_the_original_memory_retrieval_import_profile') }}</p><p v-if="item.error" class="danger-text">{{ item.error }}</p><div class="component-actions"><button class="button primary" :disabled="!!busy || !isDesktop" @click="componentAction(item.id, 'install')"><Download :size="14"/>{{ item.version ? t(item.updateAvailable ? 'ui.download_update' : 'updates.core_check_and_update') : t('ui.install') }}</button><button class="button secondary" :disabled="!!busy || !isDesktop" @click="importPackage(item.id)"><FolderOpen :size="14"/>{{ t('ui.import_offline_package') }}</button><button v-if="item.version" class="button secondary" :disabled="!!busy" @click="componentAction(item.id, item.running ? 'stop' : 'start')"><Square v-if="item.running" :size="13"/><Play v-else :size="13"/>{{ item.running ? t('ui.stop') : t('ui.start') }}</button><button v-if="item.running && coreRestartRequired" class="button secondary" :disabled="!!busy" @click="componentAction(item.id, 'restart')"><RefreshCw :size="14"/>{{ t('analysis.restart_apply') }}</button><button v-if="item.version && !usable" class="text-button" :disabled="!!busy || !item.running" @click="checkCore">{{ t('ui.check_readiness') }}</button><button class="text-button" @click="visit('https://github.com/kldhsh123/' + item.name)">{{ t('ui.original_project') }}<ExternalLink :size="12"/></button><button v-if="item.version" class="text-button" :disabled="!!busy" @click="viewLog(item.id)">{{ t('ui.logs') }}</button></div><small class="muted">{{ t('updates.core_source_hint') }}</small></div></article></div>
          <div class="note-line"><ShieldCheck :size="17"/><span>{{ t('ui.offline_packages_require_componentjson_and_a_complete') }}</span></div><p class="data-path"><FolderOpen :size="14"/>{{ dataDir }}</p>
        </template>

        <template v-if="page === 'advanced' && currentInstanceId">
          <AnalysisPanel :key="currentInstanceId" :instance-id="currentInstanceId" :ready="usable" :preferences="settings.analysis" :pending-apply="JSON.stringify(settings.analysis) !== JSON.stringify(applied?.analysis)" :settings-busy="!!busy" @update:preferences="settings.analysis = $event" @save="saveAnalysisPreferences()" @apply="saveAnalysisPreferences(true)" @error="notify($event, true)" @busy="setPanelBusy('analysis', $event)"/>
          <HistoryImagesPanel :key="'images-' + currentInstanceId" :instance-id="currentInstanceId" :ready="usable" :vision-enabled="saved.services.imageImportVision || saved.services.vision !== 'off'" :disabled="!!busy" @error="notify($event, true)" @busy="setPanelBusy('history-images', $event)" @core-change="refresh"/>
          <StickersPanel :key="'stickers-' + currentInstanceId" :instance-id="currentInstanceId" :ready="usable" :disabled="!!busy" @error="notify($event, true)" @busy="setPanelBusy('stickers', $event)"/>
        </template>


        <footer v-if="page === 'welcome'" class="setup-footer"><span><ShieldCheck :size="14"/>{{ t('ui.your_progress_is_saved_so_you_can') }}</span><div><button v-if="step > 0" class="button ghost" :disabled="!!busy" @click="previousStep"><ArrowLeft :size="15"/>{{ t('ui.back') }}</button><button v-if="step < 4" class="button primary" :disabled="!!busy || (step === 3 && !usable)" @click="nextStep">{{ step === 0 ? locale === 'en-US' ? t('ui.save_continue') : t('ui.continue_with') + presetName(settings) + t('ui.preset') : step === 3 ? t(files.length ? 'ui.save_progress_continue' : 'setup.skip_import') : t('ui.save_continue') }}<ArrowRight :size="15"/></button><button v-else class="button primary" :disabled="!!busy" @click="finish">{{ usable ? t('ui.start_chatting') : t('ui.save_settings_open_chat') }}<ArrowRight :size="15"/></button></div></footer>
        <footer v-if="page === 'settings'" class="setup-footer"><span><Circle :size="10" :fill="hasChanges ? '#9a663b' : 'none'"/>{{ hasChanges ? t('ui.unsaved_changes') : pendingApply ? t('ui.settings_saved_restart_the_core_to_apply') : t('ui.current_settings_applied') }}</span><div><button class="button ghost" :disabled="!hasChanges || !!busy" @click="settings = parseSettings(saved)">{{ t('ui.discard_changes') }}</button><button class="button primary" :disabled="!hasChanges || !!busy" @click="save"><Check :size="15"/>{{ t('ui.save_settings') }}</button></div></footer>
        </div></Transition>
        <ChatPanel v-if="currentInstanceId" v-show="page === 'chat'" ref="chatPanel" :key="currentInstanceId" :instance-id="currentInstanceId" :ready="usable && (!busy || busy === 'chat')" :self-name="settings.selfName" :friend-name="settings.friendName" :preset-label="presetName(settings)" :human-delay="settings.humanDelay" :vision-enabled="saved.services.vision !== 'off'" :debug-enabled="debugAvailable" @debug="openDebug" @error="notify($event, true)" @busy="busy = $event ? 'chat' : ''" @settings="page = 'settings'" @setup="page = 'welcome'" @import="importOpen = true"/>
      </div>
    </main>
    <DebugDrawer v-if="debugOpen && debugAvailable && currentInstanceId" :key="currentInstanceId" :instance-id="currentInstanceId" :conversation-id="debugConversationId" :initial-query="debugQuery" :full-payloads="saved.debug.fullPayloads && applied?.debug.fullPayloads === true" :external-busy="!!busy && busy !== 'debug'" @close="debugOpen = false" @busy="setPanelBusy('debug', $event)"/>
    <dialog ref="importDialog" class="import-dialog" aria-labelledby="import-dialog-title" @cancel.prevent="importOpen = false" @click="closeImportBackdrop">
      <div class="import-dialog-heading"><div><span class="eyebrow">{{ t('ui.keep_real_memories') }}</span><h2 id="import-dialog-title">{{ t('ui.bring_your_conversations_here') }}</h2></div><button class="icon-button" autofocus :aria-label="t('import.close')" @click="importOpen = false"><X :size="20"/></button></div>
      <p class="import-dialog-description">{{ t('import.dialog_hint') }}</p>
      <ImportRecords v-if="importOpen" :files="files" :preview-files="previewFiles" :candidates="candidates" v-model:self-uids="selfUids" v-model:friend-uids="friendUids" :task="task" :dragover="dragover" :busy="busy" :ready="usable" :identity-selection-valid="identitySelectionValid" :recovery="importRecovery" :recovery-error="importRecoveryError" @retry-core="retryImportCore" @pick="pickFiles" @preview="addPreviewFiles" @drop="dropFiles" @drag="dragover = $event" @remove-file="files.splice($event, 1)" @remove-preview="previewFiles.splice($event, 1)" @reanalyze="reanalyzeFile" @start="startImport" @cancel="cancelImport" @manage-core="manageCore"/>
    </dialog>
    <div v-if="showInstanceDialog" class="modal-backdrop" @click.self="showInstanceDialog = false" @keydown.esc="showInstanceDialog = false"><section class="instance-dialog" role="dialog" aria-modal="true" aria-labelledby="instance-dialog-title"><div class="section-heading"><h2 id="instance-dialog-title">{{ t('instances.create') }}</h2><button class="icon-button" :aria-label="t('common.cancel')" @click="showInstanceDialog = false"><X :size="18"/></button></div><p>{{ t('instances.description') }}</p><form @submit.prevent="createInstance"><label>{{ t('instances.name') }}<input ref="instanceNameInput" v-model="instanceName" maxlength="80" required :placeholder="t('instances.name_placeholder')"/></label><p class="muted">{{ t('instances.installations') }}</p><div class="dialog-actions"><button type="button" class="button secondary" :disabled="!!busy" @click="showInstanceDialog = false">{{ t('common.cancel') }}</button><button class="button primary" type="submit" :disabled="!!busy || !instanceName.trim()"><Plus :size="15"/>{{ t('instances.create') }}</button></div></form></section></div>
    <Transition name="toast"><div v-if="toast" class="toast-message" :class="{ error: toast.error }" role="status"><AlertCircle v-if="toast.error" :size="18"/><CheckCircle2 v-else :size="18"/><span>{{ toast.text }}</span><button class="icon-button" :aria-label="t('ui.dismiss_notification')" @click="toast = null"><X :size="14"/></button></div></Transition>
    <div v-if="lastLog" class="modal-backdrop" @click.self="lastLog = ''"><section class="log-modal" role="dialog" aria-modal="true" :aria-label="logTitle + t('ui.logs_203')"><div class="section-heading"><h2>{{ logTitle }} {{ t('ui.logs_204') }}</h2><button class="icon-button" :aria-label="t('ui.close_logs')" @click="lastLog = ''"><X :size="20"/></button></div><pre>{{ lastLog }}</pre></section></div>
  </div>
</template>
