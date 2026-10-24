import { ref, watch } from 'vue'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'

export const dictionaries = { 'zh-CN': zhCN, 'en-US': enUS }
export type Locale = keyof typeof dictionaries
export type TranslationKey = keyof typeof zhCN
export const supportedLocales = [{ id: 'zh-CN', name: '简体中文' }, { id: 'en-US', name: 'English' }] as const
const storageKey = 'afterglow.desktop.locale'
function initialLocale(): Locale {
  try { const saved = localStorage.getItem(storageKey); if (saved && saved in dictionaries) return saved as Locale } catch { /* Storage may be disabled. */ }
  return typeof navigator !== 'undefined' && !navigator.language.toLowerCase().startsWith('zh') ? 'en-US' : 'zh-CN'
}
export const locale = ref<Locale>(initialLocale())
export function setLocale(value: string): void {
  if (value in dictionaries) locale.value = value as Locale
}
export function translate(language: Locale, key: TranslationKey, args: Record<string, string | number> = {}): string {
  const text = (dictionaries[language] as Record<string, string>)[key] ?? zhCN[key] ?? key
  return text.replace(/\{([A-Za-z0-9_]+)\}/g, (match, name) => String(args[name] ?? match))
}
export function t(key: TranslationKey, args: Record<string, string | number> = {}): string { return translate(locale.value, key, args) }
watch(locale, value => {
  try { localStorage.setItem(storageKey, value) } catch { /* Keep the choice in memory. */ }
  if (typeof document !== 'undefined') { document.documentElement.lang = value; document.title = translate(value, 'app.title') }
}, { immediate: true })
