import test from 'node:test'
import assert from 'node:assert/strict'
import { defaultSettings, parseSettings, applyPreset, requiredProviders, providerIssue, channelDefaults, defaultConcurrency } from '../src/domain/settings'
import { locale, setLocale } from '../src/i18n'

test('image import model is independent, optional and remains manual in English', () => {
  const settings = defaultSettings('en-US')
  assert.equal(settings.services.imageImportVision, false)
  assert.equal(settings.providers.imageImportVision.channel, 'custom')
  assert.equal(settings.providers.imageImportVision.baseUrl, '')
  assert.equal(settings.providers.imageImportVision.model, '')
  assert.ok(!requiredProviders(settings).includes('imageImportVision'))
  settings.services.imageImportVision = true
  settings.providers.imageImportVision = { channel: 'custom', baseUrl: 'https://history.example/v1', model: 'image-model', protocol: 'responses', concurrency: 2, verification: 'skipped' }
  const saved = parseSettings(settings)
  assert.equal(saved.services.vision, 'off')
  assert.equal(saved.services.imageImportVision, true)
  assert.ok(requiredProviders(saved).includes('imageImportVision'))
  assert.deepEqual(saved.providers.imageImportVision, settings.providers.imageImportVision)
  assert.equal(providerIssue('imageImportVision', saved.providers.imageImportVision, true), '')
})

test('debug migration is opt-in and disabling it clears full payload recording', () => {
  assert.deepEqual(defaultSettings('en-US').debug, { enabled: false, fullPayloads: false })
  assert.deepEqual(parseSettings({ version: 1 }).debug, { enabled: false, fullPayloads: false })
  const enabled = parseSettings({ debug: { enabled: true, fullPayloads: true } })
  assert.deepEqual(enabled.debug, { enabled: true, fullPayloads: true })
  assert.deepEqual(applyPreset(enabled, 'careful').debug, enabled.debug)
  assert.deepEqual(parseSettings({ debug: { enabled: false, fullPayloads: true } }).debug, { enabled: false, fullPayloads: false })
})

test('DeepSeek preset fills v4-pro while English and existing model choices stay editable', () => {
  assert.equal(defaultSettings('zh-CN').providers.deepseek.model, 'deepseek-v4-pro')
  assert.equal(channelDefaults('deepseek', 'deepseek').model, 'deepseek-v4-pro')
  assert.equal(defaultSettings('en-US').providers.deepseek.model, '')
  assert.equal(defaultSettings('en-US').providers.deepseek.channel, 'custom')
  const settings = defaultSettings('zh-CN')
  settings.providers.deepseek.model = 'my-existing-model'
  assert.equal(parseSettings(settings).providers.deepseek.model, 'my-existing-model')
})

test('embedding and reranking use separate configurable channels', () => {
  const settings = defaultSettings()
  assert.equal(settings.providers.embedding.channel, 'xunfei')
  assert.equal(settings.providers.rerank.channel, 'xunfei')
  assert.equal(settings.providers.embedding.model, 'xop3qwen8bembedding')
  assert.equal(settings.providers.rerank.model, 'xop3qwen8breranker')
})

test('balanced enables a generic reranker without selecting its provider', () => {
  const settings = applyPreset(defaultSettings(), 'balanced')
  assert.equal(settings.features.rerank, true)
  assert.equal(settings.providers.rerank.channel, 'xunfei')
  assert.equal(settings.providers.rerank.channel, defaultSettings().providers.rerank.channel)
})

test('custom OpenAI-compatible channel values persist through settings parsing', () => {
  const settings = defaultSettings()
  settings.providers.deepseek = { channel: 'custom', baseUrl: 'https://api.example.test/v1', model: 'chat-model' }
  assert.deepEqual(parseSettings(settings).providers.deepseek, { ...settings.providers.deepseek, concurrency: 4 })
})

test('Responses protocol persists independently for each chat model', () => {
  const settings = defaultSettings('en-US')
  settings.providers.deepseek.protocol = 'responses'
  const restored = parseSettings(settings)
  assert.equal(restored.providers.deepseek.protocol, 'responses')
  assert.equal(restored.providers.zhipu.protocol, undefined)
  assert.equal(restored.providers.deepseek.channel, 'custom')
})

test('partially saved English settings keep unconfigured services empty', () => {
  const previous = locale.value
  try {
    setLocale('en-US')
    const settings = parseSettings({ version: 1, providers: {
      deepseek: { channel: 'custom', baseUrl: 'https://my-channel.test/v1', model: 'my-model' },
    } })
    assert.equal(settings.providers.deepseek.model, 'my-model')
    for (const role of ['embedding', 'rerank', 'zhipu'] as const) {
      assert.deepEqual(settings.providers[role], { channel: 'custom', baseUrl: '', model: '', concurrency: 4 })
    }
  } finally {
    setLocale(previous)
  }
})

test('only enabled optional services become required', () => {
  const settings = defaultSettings()
  assert.deepEqual(requiredProviders(settings), ['deepseek', 'embedding', 'zhipu'])
  settings.services.vision = 'main'
  assert.equal(requiredProviders(settings).includes('vision'), false)
  settings.services.vision = 'separate'
  settings.services.webSearch = true
  assert.deepEqual(requiredProviders(settings).slice(-2), ['vision', 'search'])
  assert.deepEqual(parseSettings(settings).services, settings.services)
})

test('skipping verification never bypasses required model URL or key fields', () => {
  const profile = { channel: 'custom', baseUrl: '', model: '', verification: 'skipped' as const }
  assert.ok(providerIssue('vision', profile, true))
  profile.model = 'vision-model'
  assert.ok(providerIssue('vision', profile, true))
  profile.baseUrl = 'https://vision.example/v1'
  assert.ok(providerIssue('vision', profile, false))
  assert.equal(providerIssue('vision', profile, true), '')
  assert.ok(providerIssue('vision', { ...profile, verification: 'untested' }, true))
})

test('SearXNG needs a URL and confirmation but no mandatory key', () => {
  assert.equal(providerIssue('search', { channel: 'searxng', baseUrl: 'https://search.example', model: '', verification: 'verified' }, false), '')
  assert.ok(providerIssue('search', { channel: 'tavily', baseUrl: 'https://api.tavily.com', model: '', verification: 'skipped' }, false))
})

test('model limits migrate, persist and remain independent of reply presets', () => {
  const settings = defaultSettings('zh-CN')
  assert.equal(settings.providers.embedding.concurrency, 20)
  assert.equal(settings.providers.rerank.concurrency, 20)
  assert.equal(settings.providers.zhipu.concurrency, 20)
  assert.equal(defaultConcurrency('custom', 'glm-4-flash'), 4)
  settings.providers.embedding.concurrency = 7
  settings.providers.rerank.concurrency = 2
  settings.providers.deepseek.concurrency = 64
  assert.equal(parseSettings(applyPreset(settings, 'balanced')).providers.embedding.concurrency, 7)
  assert.equal(parseSettings(settings).providers.rerank.concurrency, 2)
  assert.equal(parseSettings(settings).providers.deepseek.concurrency, 64)
  assert.equal(parseSettings({ providers: { embedding: { channel: 'xunfei' } } }).providers.embedding.concurrency, 20)
  for (const value of [0, 65, 1.5, NaN]) {
    assert.ok(providerIssue('embedding', { ...settings.providers.embedding, concurrency: value }, true))
    assert.equal(parseSettings({ providers: { embedding: { channel: 'xunfei', concurrency: value } } }).providers.embedding.concurrency, 20)
  }
})
