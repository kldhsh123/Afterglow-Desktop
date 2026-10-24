import { t, locale } from "../i18n"
export type PresetId = 'quick' | 'balanced' | 'careful'
export type ProviderId = 'deepseek' | 'embedding' | 'rerank' | 'zhipu' | 'vision' | 'imageImportVision' | 'search'
export type FeatureId = 'rerank' | 'policy' | 'rewrite'
export interface Features { rerank: boolean; policy: boolean; rewrite: boolean }
export interface ProviderSettings { channel: string; baseUrl: string; model: string; concurrency?: number; protocol?: 'chat_completions' | 'responses'; verification?: 'untested' | 'verified' | 'skipped' }
export interface AnalysisPreferences { personalityPrompt: boolean; lifeContext: boolean }
export interface DebugPreferences { enabled: boolean; fullPayloads: boolean }
export interface Settings { debug: DebugPreferences; analysis: AnalysisPreferences; version: 1; preset: PresetId; features: Features; services: { vision: 'off' | 'main' | 'separate'; imageImportVision: boolean; webSearch: boolean; webFetch: boolean }; humanDelay: boolean; selfName: string; friendName: string; relationship: string; providers: Record<ProviderId, ProviderSettings>; onboardingStep: number; configured: boolean }
const chatChannels = {
  deepseek: { baseUrl: 'https://api.deepseek.com/v1', model: 'deepseek-v4-pro', keyUrl: 'https://platform.deepseek.com/api_keys' },
  zhipu: { baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash', keyUrl: 'https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys' },
}
export function defaultConcurrency(channel: string, model: string): number {
  return channel === 'xunfei' || (channel === 'zhipu' && model === 'glm-4-flash') ? 20 : 4
}
export function providerConcurrency(profile: ProviderSettings): number {
  return Number.isInteger(profile.concurrency) && profile.concurrency! >= 1 && profile.concurrency! <= 64
    ? profile.concurrency! : defaultConcurrency(profile.channel, profile.model)
}
export function channelsFor(id: ProviderId): { value: string; label: string }[] {
  if (id === 'vision' || id === 'imageImportVision') return [{ value: 'custom', label: t('ui.custom_openai_compatible_api') }]
  if (id === 'search') return [{ value: 'tavily', label: 'Tavily' }, { value: 'searxng', label: 'SearXNG' }]
  const official = id === 'deepseek' || id === 'zhipu'
    ? [{ value: 'deepseek', label: 'DeepSeek API' }, { value: 'zhipu', label: t('channels.zhipu') }]
    : [{ value: 'xunfei', label: t('channels.xunfei') }]
  return [...official, { value: 'custom', label: t('ui.custom_openai_compatible_api') }]
}
export function channelDefaults(id: ProviderId, channel: string): ProviderSettings {
  if (id === 'search') return { channel, baseUrl: channel === 'tavily' ? 'https://api.tavily.com' : '', model: '', verification: 'untested' }
  if ((id === 'deepseek' || id === 'zhipu') && channel in chatChannels) {
    const { baseUrl, model } = chatChannels[channel as keyof typeof chatChannels]
    return { channel, baseUrl, model, concurrency: defaultConcurrency(channel, model), verification: 'untested' }
  }
  const definition = providerDefinitions.find(p => p.id === id)!
  const model = channel === 'custom' ? '' : definition.defaultModel
  return { channel, baseUrl: channel === 'custom' ? '' : definition.defaultUrl, model, concurrency: defaultConcurrency(channel, model), verification: 'untested' }
}
export function channelKeyUrl(id: ProviderId, channel: string): string {
  if (channel === 'custom') return ''
  return channel in chatChannels ? chatChannels[channel as keyof typeof chatChannels].keyUrl : providerDefinitions.find(p => p.id === id)!.keyUrl
}
export const presets: { id: PresetId; name: string; tagline: string; description: string; tradeoff: string; features: Features }[] = [
  { id: 'quick', get name() { return t("ui.quick") }, get tagline() { return t("ui.less_waiting_easy_conversation") }, get description() { return t("ui.keeps_chat_and_basic_memory_retrieval_with") }, get tradeoff() { return t("ui.quick_is_recommended_complex_wording_gets_less") }, features: { rerank: false, policy: false, rewrite: false } },
  { id: 'balanced', get name() { return t("ui.balanced") }, get tagline() { return t("ui.refine_relevant_memories") }, get description() { return t("ui.uses_configured_reranking_channel_to_select_relevant_passages") }, get tradeoff() { return t("ui.an_extra_memory_selection_step_may_add") }, features: { rerank: true, policy: false, rewrite: false } },
  { id: 'careful', get name() { return t("ui.careful") }, get tagline() { return t("ui.a_little_more_consideration") }, get description() { return t("ui.enables_reranking_tone_assessment_and_retrieval_query") }, get tradeoff() { return t("ui.extra_auxiliary_model_calls_may_take_longer") }, features: { rerank: true, policy: true, rewrite: true } },
]
export const featureDefinitions: { id: FeatureId; label: string; description: string; cost: string }[] = [
  { id: 'rerank', get label() { return t("ui.refine_memory_relevance") }, get description() { return t("ui.ranks_retrieved_conversation_passages_by_relevance") }, get cost() { return t("ui.adds_one_reranking_request_and_may") } },
  { id: 'policy', get label() { return t("ui.consider_tone_before_replying") }, get description() { return t("ui.adds_an_interaction_strategy_check_before_generation") }, get cost() { return t("ui.adds_zhipu_auxiliary_model_calls_and_may") } },
  { id: 'rewrite', get label() { return t("ui.expand_short_expressions") }, get description() { return t("ui.expands_brief_queries_for_retrieval_without_changing") }, get cost() { return t("ui.adds_auxiliary_model_calls_extra_processing_may") } },
]
export const providerDefinitions: { id: ProviderId; name: string; role: string; description: string; keyUrl: string; defaultChannel: string; defaultUrl: string; defaultModel: string }[] = [
  { id: 'deepseek', get name() { return t("services.main_model") }, get role() { return t("ui.generates_chat_replies") }, get description() { return t("services.main_description") }, keyUrl: 'https://platform.deepseek.com/api_keys', defaultChannel: 'deepseek', defaultUrl: 'https://api.deepseek.com/v1', defaultModel: chatChannels.deepseek.model },
  { id: 'embedding', get name() { return t("ui.memory_embedding") }, get role() { return t("ui.builds_the_memory_index") }, get description() { return t("ui.embedding_api_key_is_separate_from_reranking") }, keyUrl: 'https://maas.xfyun.cn/modelSquare/base/2529035470232577', defaultChannel: 'xunfei', defaultUrl: 'https://maas-api.cn-huabei-1.xf-yun.com/v2', defaultModel: 'xop3qwen8bembedding' },
  { id: 'rerank', get name() { return t("ui.memory_reranking") }, get role() { return t("ui.reranks_retrieved_memories") }, get description() { return t("ui.reranking_is_optional_and_uses_its_own_key") }, keyUrl: 'https://maas.xfyun.cn/modelSquare/base/2529035707210755', defaultChannel: 'xunfei', defaultUrl: 'https://maas-api.cn-huabei-1.xf-yun.com/v2', defaultModel: 'xop3qwen8breranker' },
  { id: 'zhipu', get name() { return t("services.small_model") }, get role() { return t("ui.provides_auxiliary_processing") }, get description() { return t("services.small_description") }, keyUrl: 'https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys', defaultChannel: 'zhipu', defaultUrl: 'https://open.bigmodel.cn/api/paas/v4', defaultModel: 'glm-4-flash' },
  { id: 'vision', get name() { return t('services.vision') }, get role() { return t('services.vision_role') }, get description() { return t('services.vision_description') }, keyUrl: '', defaultChannel: 'custom', defaultUrl: '', defaultModel: '' },
  { id: 'imageImportVision', get name() { return t('services.image_import_vision') }, get role() { return t('services.image_import_vision_role') }, get description() { return t('services.image_import_vision_description') }, keyUrl: '', defaultChannel: 'custom', defaultUrl: '', defaultModel: '' },
  { id: 'search', get name() { return t('services.search') }, get role() { return t('services.search_role') }, get description() { return t('services.search_description') }, keyUrl: 'https://app.tavily.com', defaultChannel: 'tavily', defaultUrl: 'https://api.tavily.com', defaultModel: '' },
]
export function defaultSettings(language = locale.value): Settings {
  const providers = Object.fromEntries(providerDefinitions.map(p => {
    const profile: ProviderSettings = language === 'en-US'
      ? { channel: p.id === 'search' ? 'tavily' : 'custom', baseUrl: '', model: '' }
      : { channel: p.defaultChannel, baseUrl: p.defaultUrl, model: p.defaultModel }
    if (p.id !== 'search') profile.concurrency = defaultConcurrency(profile.channel, profile.model)
    return [p.id, profile]
  })) as Settings['providers']
  return { debug: { enabled: false, fullPayloads: false }, analysis: { personalityPrompt: false, lifeContext: false }, version: 1, preset: 'quick', features: { ...presets[0].features }, services: { vision: 'off', imageImportVision: false, webSearch: false, webFetch: false }, humanDelay: false, selfName: '', friendName: '', relationship: 'friend', providers, onboardingStep: 0, configured: false }
}
export function applyPreset(settings: Settings, id: PresetId): Settings { const preset = presets.find(p => p.id === id); if (!preset) throw new Error(t("ui.unknown_preset")); return { ...settings, preset: id, features: { ...preset.features } } }
export function isCustomized(settings: Settings): boolean { const expected = presets.find(p => p.id === settings.preset)!.features; return featureDefinitions.some(f => settings.features[f.id] !== expected[f.id]) }
export function presetName(settings: Settings): string { if (locale.value === 'en-US') return t('ui.manual_configuration'); const name = presets.find(p => p.id === settings.preset)!.name; return isCustomized(settings) ? t("ui.custom_based_on") + name : name }
export function parseSettings(input: unknown): Settings {
  const defaults = defaultSettings(); if (!input || typeof input !== 'object') return defaults; const value = input as Partial<Settings>;
  const preset = presets.some(p => p.id === value.preset) ? value.preset! : defaults.preset; const base = applyPreset(defaults, preset);
  const features = Object.fromEntries(featureDefinitions.map(f => [f.id, typeof value.features?.[f.id] === 'boolean' ? value.features[f.id] : base.features[f.id]])) as unknown as Features;
  const old = value.providers as Record<string, { model?: unknown }> | undefined
  const providers = Object.fromEntries(providerDefinitions.map(p => {
    const raw = (value.providers as Record<string, Partial<ProviderSettings>> | undefined)?.[p.id]
    const legacy = p.id === 'embedding' ? old?.xunfei : undefined
    const model = raw?.model ?? legacy?.model
    const fallback = legacy ? { channel: p.defaultChannel, baseUrl: p.defaultUrl, model: p.defaultModel } : defaults.providers[p.id]
    const profile: ProviderSettings = { channel: typeof raw?.channel === 'string' ? raw.channel.slice(0, 80) : fallback.channel, baseUrl: typeof raw?.baseUrl === 'string' ? raw.baseUrl.slice(0, 500) : fallback.baseUrl, model: typeof model === 'string' ? model.slice(0, 160) : fallback.model, ...(raw?.protocol === 'responses' ? { protocol: 'responses' as const } : {}), ...(raw?.verification === 'skipped' || raw?.verification === 'verified' ? { verification: raw.verification } : {}) }
    if (p.id !== 'search') profile.concurrency = providerConcurrency({ ...profile, concurrency: raw?.concurrency })
    return [p.id, profile]
  })) as Settings['providers']
  const services = { vision: ['main', 'separate'].includes(value.services?.vision ?? '') ? value.services!.vision : 'off' as const, imageImportVision: value.services?.imageImportVision === true, webSearch: value.services?.webSearch === true, webFetch: value.services?.webFetch === true }
  return { ...base, debug: { enabled: value.debug?.enabled === true, fullPayloads: value.debug?.enabled === true && value.debug?.fullPayloads === true }, analysis: { personalityPrompt: value.analysis?.personalityPrompt === true, lifeContext: value.analysis?.lifeContext === true }, features, services, humanDelay: value.humanDelay === true, selfName: typeof value.selfName === 'string' ? value.selfName.slice(0, 80) : '', friendName: typeof value.friendName === 'string' ? value.friendName.slice(0, 80) : '', relationship: ['friend', 'lover', 'family', 'colleague'].includes(value.relationship ?? '') ? value.relationship! : 'friend', providers, onboardingStep: Number.isInteger(value.onboardingStep) ? Math.min(4, Math.max(0, value.onboardingStep!)) : 0, configured: value.configured === true }
}

export function requiredProviders(settings: Settings): ProviderId[] {
  return ['deepseek', 'embedding', 'zhipu', ...(settings.features.rerank ? ['rerank'] : []), ...(settings.services.vision === 'separate' ? ['vision'] : []), ...(settings.services.imageImportVision ? ['imageImportVision'] : []), ...(settings.services.webSearch ? ['search'] : [])] as ProviderId[]
}
export function providerIssue(id: ProviderId, profile: ProviderSettings, hasKey: boolean, requireVerification = true): string {
  if (id !== 'search' && profile.concurrency !== undefined && (!Number.isInteger(profile.concurrency) || profile.concurrency < 1 || profile.concurrency > 64)) return t('concurrency.invalid')
  if (id !== 'search' && !profile.model.trim()) return t('setup.model_required')
  if (profile.channel === 'custom' || id === 'search') {
    try { const url = new URL(profile.baseUrl); if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.search || url.hash) return t('setup.url_required') } catch { return t('setup.url_required') }
  }
  if (!hasKey && !(id === 'search' && profile.channel === 'searxng')) return t('setup.key_required')
  if (requireVerification && !['verified', 'skipped'].includes(profile.verification ?? '')) return t('setup.test_required')
  return ''
}
