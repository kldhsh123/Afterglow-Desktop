import { locale, t } from "../i18n"
import { invoke } from '@tauri-apps/api/core'
import { open } from '@tauri-apps/plugin-dialog'
import { openUrl } from '@tauri-apps/plugin-opener'
import { defaultSettings, parseSettings, type Settings } from '../domain/settings'
import { ref } from 'vue'

export const isDesktop = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
export type ComponentId = 'core'
export interface ComponentInfo { id: ComponentId; name: string; version: string | null; running: boolean; availableVersion: string | null; updateAvailable?: boolean; state: string; error: string }
export interface ExtensionInfo { id: 'qq' | 'weixin'; name: string; running: boolean; state: string; configured: boolean; credentialsReady: boolean; pendingUsers?: { uid: string; openid: string; code: string; createdAt: number }[]; contacts?: { uid: string; name: string }[]; qrContent?: string; verifyCodeRequired?: boolean; error: string }
export interface InstanceInfo { id: string; name: string; path: string; running: boolean }
export interface Bootstrap { settings: Settings | null; applied: Settings | null; restartRequired?: boolean; credentials: string[]; components: ComponentInfo[]; extensions: ExtensionInfo[]; dataDir: string; platform: string; instanceId: string; instances: InstanceInfo[]; installationDir: string }
export interface Result { ok: boolean; message: string; models?: string[] }
const STORAGE_KEY = 'afterglow.desktop.settings.v1'
const INSTANCE_KEY = 'afterglow.desktop.instances.v1'
export const currentInstanceId = ref('')
function previewInstances(): { active: string; instances: InstanceInfo[] } {
  try {
    const state = JSON.parse(localStorage.getItem(INSTANCE_KEY) ?? 'null')
    if (state && Array.isArray(state.instances) && state.instances.every((i: InstanceInfo) => typeof i.id === 'string' && /^[a-z0-9_-]+$/.test(i.id) && typeof i.name === 'string') && state.instances.some((i: InstanceInfo) => i.id === state.active)) return state
  } catch { /* Ignore malformed preview metadata. */ }
  return { active: 'default', instances: [{ id: 'default', name: '', path: '', running: false }] }
}
const previewComponents: ComponentInfo[] = [
  { id: 'core', name: 'Afterglow', version: null, availableVersion: null, running: false, state: 'not_installed', error: '' },
]
export async function rpc<T>(method: string, args: Record<string, unknown> = {}): Promise<T> {
  const instanceId = args.instanceId ?? (currentInstanceId.value || undefined)
  if (isDesktop) return invoke<T>('host_request', { method, args: { ...args, ...(instanceId ? { instanceId } : {}), locale: locale.value } })
  const state = previewInstances()
  const selected = String(instanceId ?? state.active)
  if (method === 'create_instance') {
    const name = typeof args.name === 'string' ? args.name.trim() : ''
    if (!name || name.length > 80) throw new Error(t('host.invalid_instance_name'))
    const id = crypto.randomUUID().replaceAll('-', '').slice(0, 16)
    state.instances.push({ id, name, path: '', running: false })
    localStorage.setItem(INSTANCE_KEY, JSON.stringify(state))
    return { ok: true, id, message: t('host.instance_created') } as T
  }
  if (method === 'switch_instance') {
    if (!state.instances.some(i => i.id === args.id)) throw new Error(t('host.instance_not_found'))
    state.active = String(args.id)
    localStorage.setItem(INSTANCE_KEY, JSON.stringify(state))
    return { ok: true, id: state.active, message: t('host.instance_selected') } as T
  }
  if (!state.instances.some(i => i.id === selected)) throw new Error(t('host.instance_not_found'))
  if (method === 'bootstrap') {
    let saved: Settings | null = null
    try { const raw = localStorage.getItem(STORAGE_KEY + '.' + selected) ?? (selected === 'default' ? localStorage.getItem(STORAGE_KEY) : null); saved = raw ? parseSettings(JSON.parse(raw)) : null } catch { /* invalid preview state is not trusted */ }
    return { settings: saved, applied: null, credentials: [], components: previewComponents, extensions: [{ id: 'qq', name: 'QQ', running: false, state: 'stopped', configured: false, credentialsReady: false, error: '' }, { id: 'weixin', name: 'WeChat', running: false, state: 'stopped', configured: false, credentialsReady: false, error: '' }], dataDir: t("ui.the_windows_desktop_app_creates_your_data"), platform: 'browser', instanceId: selected, instances: state.instances.map(i => ({ ...i, name: i.name || t('instances.default') })), installationDir: '' } as T
  }
  if (method === 'save_settings') {
    const settings = parseSettings(args.settings ?? defaultSettings())
    localStorage.setItem(STORAGE_KEY + '.' + selected, JSON.stringify(settings))
    return { ok: true, message: t("ui.preferences_saved_in_this_browser_running_components") } as T
  }
  if (method === 'extension_status') return { extensions: [{ id: 'qq', name: 'QQ', state: 'stopped', running: false, credentialsReady: false }, { id: 'weixin', name: 'WeChat', state: 'stopped', running: false, credentialsReady: false }] } as T
  if (method === 'status') return { components: previewComponents, port: null } as T
  if (method === 'list_conversations') return { conversations: [] } as T
  throw new Error(t("ui.this_action_requires_the_windows_app_browser"))
}
export async function chooseFiles(component = false): Promise<string[]> {
  if (!isDesktop) throw new Error(t("ui.local_file_selection_requires_the_windows_app"))
  const selected = await open({ multiple: !component, filters: [{ name: component ? t("ui.afterglow_component_package") : t("ui.chat_export_files"), extensions: component ? ['zip'] : ['json', 'jsonl', 'ndjson', 'txt', 'md', 'html', 'htm'] }] })
  return selected ? typeof selected === 'string' ? [selected] : selected : []
}
export async function openExternal(url: string) {
  const parsed = new URL(url)
  if (parsed.protocol !== 'https:') throw new Error(t("ui.only_https_links_are_allowed"))
  if (isDesktop) await openUrl(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}
export async function chooseImages(single = false): Promise<string[]> {
  const selected = await open({ multiple: !single, filters: [{ name: t('chat.images'), extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp'] }] })
  return selected ? typeof selected === 'string' ? [selected] : selected : []
}

export async function chooseDirectory(): Promise<string | null> {
  if (!isDesktop) throw new Error(t('ui.local_file_selection_requires_the_windows_app'))
  const selected = await open({ directory: true, multiple: false, title: t('media.choose_directory') })
  return typeof selected === 'string' ? selected : null
}
