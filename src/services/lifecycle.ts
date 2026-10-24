import { ref, watch } from 'vue'
import { invoke } from '@tauri-apps/api/core'
import { isDesktop } from './desktop'
import { locale } from '../i18n'

export type CloseAction = 'ask' | 'tray' | 'exit'
export interface DesktopPreferences { closeAction: CloseAction; autostart: boolean; trayAvailable: boolean }
export const desktopPreferences = ref<DesktopPreferences>({ closeAction: 'ask', autostart: false, trayAvailable: false })
let loading: Promise<void> | undefined
let pendingSave = Promise.resolve()

export function loadDesktopPreferences(): Promise<void> {
  if (!loading) loading = (async () => {
    if (isDesktop) desktopPreferences.value = await invoke<DesktopPreferences>('desktop_preferences')
  })().catch(error => { loading = undefined; throw error })
  return loading
}

export function saveDesktopPreferences(changes: Partial<Pick<DesktopPreferences, 'closeAction' | 'autostart'>>): Promise<void> {
  const args = { ...changes, locale: locale.value }
  // A slow locale update must not overwrite the response to a newer user choice.
  const task = pendingSave.catch(() => {}).then(async () => {
    await loadDesktopPreferences()
    if (isDesktop) desktopPreferences.value = await invoke<DesktopPreferences>('set_desktop_preferences', { args })
    else desktopPreferences.value = { ...desktopPreferences.value, ...changes }
  })
  pendingSave = task
  return task
}

export async function applyCloseAction(action: Exclude<CloseAction, 'ask'>): Promise<void> {
  if (!isDesktop) return
  await invoke(action === 'tray' ? 'hide_to_tray' : 'exit_application')
}

// Keep native tray strings in step with the language picker as well as settings.
// This changes locale only; it never registers or disables Windows startup.
if (isDesktop) watch(locale, () => {
  void loadDesktopPreferences().then(() => saveDesktopPreferences({})).catch(() => {})
}, { immediate: true })
