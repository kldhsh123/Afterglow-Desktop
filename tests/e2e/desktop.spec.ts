import { test, expect, type Page } from '@playwright/test'

async function desktop(page: Page, firstRun = false, query = '') {
  await page.addInitScript(() => {
    localStorage.setItem('afterglow.desktop.locale', 'zh-CN')
    const state = {
      settings: JSON.parse(sessionStorage.getItem('fixture-settings') ?? 'null') as any,
      applied: null as any,
      appliedInitialized: false,
      restartRequired: false,
      healthReady: !location.search.includes('slow-core'),
      credentials: JSON.parse(sessionStorage.getItem('fixture-credentials') ?? (location.search.includes('first-run') ? '[]' : '["deepseek","embedding","zhipu"]')) as string[],
      calls: [] as { method: string; args: any }[],
      preferences: { ...JSON.parse(sessionStorage.getItem('fixture-desktop-preferences') ?? '{"closeAction":"ask","autostart":false}'), trayAvailable: !location.search.includes('no-tray') },
      conversation: null as any,
      conversations: [] as any[],
      analysisArtifacts: { personalityPrompt: false, lifeContext: false },
      analysisTask: null as any,
      analysisDiagnostics: null as any,
      analysisHoldStatus: false,
      analysisPendingStatus: [] as { id: string; resolve: (value: any) => void }[],
      core: { id: 'core', name: 'Afterglow', version: location.search.includes('needs-core') ? null : '0.4.0', running: !location.search.includes('needs-core'), availableVersion: '0.4.0', state: 'stopped' },
      weixin: { id: 'weixin', name: 'WeChat', running: false, state: 'stopped', configured: false, credentialsReady: false, error: '', qrContent: '', verifyCodeRequired: false, pendingUsers: [] as any[], contacts: [] as any[] },
    }
    ;(window as any).__test = state
    let callbackId = 0
    const callbacks = new Map<number, (event: any) => unknown>()
    const listeners = new Map<number, { event: string; handler: number }>()
    ;(window as any).__test.emitClose = async () => {
      for (const [id, listener] of listeners) {
        if (listener.event === 'desktop-close-requested') await callbacks.get(listener.handler)?.({ event: listener.event, id, payload: {} })
      }
    }
    const qq = { id: 'qq', name: 'QQ', running: false, state: 'stopped', configured: false, credentialsReady: false, error: '' }
    ;(window as any).__TAURI_EVENT_PLUGIN_INTERNALS__ = { unregisterListener(_event: string, id: number) { listeners.delete(id) } }
    ;(window as any).__TAURI_INTERNALS__ = {
      metadata: { currentWebview: { label: 'main' }, currentWindow: { label: 'main' } },
      transformCallback: (callback: (event: any) => unknown) => { callbacks.set(++callbackId, callback); return callbackId },
      invoke: async (command: string, payload: any) => {
        if (command === 'desktop_preferences') return { ...state.preferences }
        if (['set_desktop_preferences', 'hide_to_tray', 'exit_application'].includes(command)) {
          state.calls.push({ method: command, args: payload?.args })
          if (command === 'hide_to_tray' && location.search.includes('minimize-fails')) throw new Error('Window action failed')
          if (command === 'set_desktop_preferences') {
            if (payload?.args?.closeAction && location.search.includes('preference-fails')) throw new Error('Preference save failed')
            Object.assign(state.preferences, payload?.args)
            sessionStorage.setItem('fixture-desktop-preferences', JSON.stringify(state.preferences))
            return { ...state.preferences }
          }
          return
        }
        if (command === 'plugin:window|is_maximized') return false
        if (command.startsWith('plugin:window|')) {
          state.calls.push({ method: command, args: payload })
          if (command === 'plugin:window|minimize' && location.search.includes('minimize-fails')) throw new Error('Window action failed')
          return
        }
        if (command === 'plugin:dialog|open') return [payload.options?.filters?.[0]?.extensions?.includes('jpg') ? 'C:\\photo.png' : 'C:\\records.json']
        if (command === 'apply_desktop_update') { state.calls.push({ method: 'apply_desktop_update', args: payload.args }); return }
        if (command === 'plugin:opener|open_url') { state.calls.push({ method: 'open_external', args: payload }); return }
        if (command === 'plugin:event|listen') { const id = listeners.size + 1; listeners.set(id, payload); return id }
        if (command.startsWith('plugin:event|')) return
        const method = payload?.method, args = payload?.args
        state.calls.push({ method, args })
        switch (method) {
          case 'bootstrap': {
            const current = state.settings ?? (location.search.includes('first-run') ? null : { version: 1, preset: 'quick', configured: true, providers: { deepseek: { model: 'test-main' } }, services: { vision: location.search.includes('vision') ? 'main' : 'off' } })
            if (!state.appliedInitialized) { state.applied = state.core.running ? structuredClone(current) : null; state.appliedInitialized = true }
            return {
            settings: current, applied: state.applied, restartRequired: state.restartRequired, credentials: state.credentials,
            components: [state.core],
            extensions: [qq, state.weixin], dataDir: 'C:\\AfterglowData', platform: 'win32',
            instanceId: args?.instanceId || 'default', instances: [{ id: 'default', name: '', running: true }, { id: 'second', name: 'Second', running: true }], installationDir: 'C:\\Afterglow',
          } }
          case 'save_settings': state.settings = args.settings; sessionStorage.setItem('fixture-settings', JSON.stringify(args.settings)); return { ok: true, message: '已保存' }
          case 'set_secret': if (!state.credentials.includes(args.name)) state.credentials.push(args.name); sessionStorage.setItem('fixture-credentials', JSON.stringify(state.credentials)); return { ok: true, message: '已保存' }
          case 'test_provider': if (location.search.includes('failed-tests')) throw new Error('测试网络不可用'); return { ok: true, message: '测试通过' }
          case 'install': state.core.version = '0.4.0'; return { ok: true, message: '已安装' }
          case 'start':
          case 'restart': state.core.running = true; state.applied = structuredClone(state.settings); state.restartRequired = false; return { ok: true, message: '已启动' }
          case 'stop': state.core.running = false; return { ok: true, message: '已停止' }
          case 'analysis_files': return { files: [{ name: 'records.json', saved_as: '/uploads/converted.json', total_messages: 2 }], task: state.analysisTask }
          case 'analysis_diagnostics': return state.analysisDiagnostics ?? { prompt_ready: { ...state.analysisArtifacts }, state: 'available', has_reports: false, events: 0, observations: 0, available_reports: [], blocks: 0, completed: 0, skipped: 0, empty_reports: [], failures: [], directory: 'C:\\AfterglowData\\profiles\\default\\core\\data\\analysis' }
          case 'stickers_list': return { items: [] }
          case 'analysis_start': state.analysisTask = { task_id: 'analysis1', status: 'pending', progress: 0, stage: 'New task pending' }; return state.analysisTask
          case 'analysis_status':
            if (state.analysisHoldStatus) return new Promise(resolve => state.analysisPendingStatus.push({ id: args.id, resolve }))
            state.analysisTask = { task_id: args.id, status: 'done', progress: 1, stage: 'Test analysis complete', report: { messages: 2 } }; return state.analysisTask
          case 'status': return { components: [state.core] }
          case 'health': if (!state.healthReady) throw new Error('Core is starting'); return { ok: true, restartRequired: state.restartRequired, applied: state.applied }
          case 'debug_snapshot': return { stats: { version: '0.4.0', memory: { friend_messages: 42 }, calls: {}, model_chain: [], database: {}, life: { snapshot: { current_activity: 'resting' } }, proactive: {}, writeback: {} }, config: { debug: { endpoints_enabled: true, model_full_payloads_enabled: false } } }
          case 'debug_search': return { fused: [{ chunk_id: 'test-memory', rank: 1, kind: 'friend_message', text: 'Retrieval fixture', score: 0.9 }], trace_id: 'retrieval-fixture' }
          case 'debug_reset_metrics': return { status: 'ok' }
          case 'debug_proactive': return { message: 'Proactive fixture', trace_id: 'proactive-fixture', silenced: false }
          case 'list_conversations': return { conversations: structuredClone(state.conversations) }
          case 'create_conversation': state.conversation = { id: state.conversations.length ? crypto.randomUUID() : '6af21773-30ed-447c-ab59-e8a2d820b981', title: '', updated_at: Date.now(), turns: [] }; state.conversations.unshift(state.conversation); return state.conversation
          case 'get_conversation': state.conversation = state.conversations.find(item => item.id === args.id); return state.conversation
          case 'delete_conversation':
            if (state.conversations.length <= 1) throw new Error('至少保留一个会话')
            state.conversations = state.conversations.filter(item => item.id !== args.id)
            if (state.conversation?.id === args.id) state.conversation = null
            return { ok: true, message: '本机会话已删除。' }
          case 'rename_conversation': {
            const item = state.conversations.find(item => item.id === args.id)
            item.title = args.title.trim()
            return item
          }
          case 'move_conversation': {
            const index = state.conversations.findIndex(item => item.id === args.id), target = index + (args.direction === 'up' ? -1 : 1)
            if (target >= 0 && target < state.conversations.length) [state.conversations[index], state.conversations[target]] = [state.conversations[target], state.conversations[index]]
            return { ok: true }
          }
          case 'read_chat_images': return { images: [{ name: 'photo.png', dataUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII=' }] }
          case 'send_chat': state.conversation.turns = [{ id: args.requestId, content: args.content, attachments: args.attachments, reply: 'Image reply', state: 'completed', error: '', created_at: Date.now() }]; return { ok: true }
          case 'desktop_update_status': return { currentVersion: '0.1.0-internal.2', availableVersion: '0.1.0-internal.3', available: true, sourceUrl: '' }
          case 'start_update_checks':
          case 'repository_update_status': return { checking: false, core: { available: false }, desktop: { available: location.search.includes('repository-update'), version: '0.1.0-internal.99' } }
          case 'download_desktop_update': if (location.search.includes('download-fails')) throw new Error('无法连接 GitHub：连接超时，请检查网络后重试。'); return { path: 'C:\\verified-installer.exe', sha256: 'a'.repeat(64) }
          case 'refresh_catalog': return { ok: true, message: '更新清单已刷新' }
          case 'reanalyze_import':
          case 'inspect_files': return { uploaded: [{
            name: 'records.json', saved_as: '/uploads/converted.json', size: 1000, format: 'afterglow_v1',
            format_label: 'AI mapping', total_messages: 2, error: '', ai_converted: true,
            conversion_stats: { source_records: 3, converted_messages: 2, skipped_records: 1 },
            candidates: [{ uid: 'alice', name: 'Alice', role_hint: 'unknown' }, { uid: 'bob', name: 'Bob', role_hint: 'unknown' }],
            identity_previews: { alice: 'Alice message', bob: 'Bob message' },
          }] }
          case 'start_import': state.restartRequired = true; return { task_id: 'test_task', status: 'pending' }
          case 'import_status': return { task_id: 'test_task', status: 'done', report: { failed_chunks: 0, files: [
            { file: 'records.json', report: { parsed_messages: 2, skipped_messages: 0, duration_seconds: 0.1,
              upserted_friend: 1, upserted_response_pairs: 1, upserted_window: 1 } },
          ] } }
          case 'extension_status': return { extensions: [qq, state.weixin] }
          case 'start_weixin_login': Object.assign(state.weixin, { running: true, state: 'verify', qrContent: 'https://weixin.qq.com/login/sample-local-qr', verifyCodeRequired: true }); return { ok: true, message: '扫码登录' }
          case 'submit_weixin_verify_code': Object.assign(state.weixin, { running: false, state: 'authenticated', credentialsReady: true, verifyCodeRequired: false, qrContent: '' }); return { ok: true, message: '登录已保存' }
          case 'start_extension': Object.assign(state.weixin, { running: true, state: 'connected', pendingUsers: [{ uid: 'owner', openid: 'owner', code: '123456', createdAt: Date.now()/1000 }] }); return { ok: true, message: '已连接' }
          case 'authorize_contact': Object.assign(state.weixin, { pendingUsers: [], contacts: args.revoke ? [] : [{ uid: 'owner', name: 'owner' }] }); return { ok: true, message: '授权已更新' }
          case 'stop_extension': Object.assign(state.weixin, { running: false, state: 'stopped' }); return { ok: true, message: '已断开' }
          case 'switch_instance': return { ok: true, message: '已切换' }
          default: throw new Error('Unexpected command: ' + command + '/' + method)
        }
      },
    }
  })
  await page.goto(query || (firstRun ? '/?first-run' : '/'), { waitUntil: 'domcontentloaded' })
}

test('waiting core refreshes automatically and core management returns to unfinished setup', async ({ page }) => {
  await page.addInitScript(() => {
    sessionStorage.setItem('fixture-settings', JSON.stringify({ version: 1, preset: 'quick', configured: false, onboardingStep: 3, providers: { deepseek: { model: 'test-main' } } }))
    sessionStorage.setItem('fixture-credentials', '["deepseek","embedding","zhipu"]')
  })
  await desktop(page, true, '/?first-run&slow-core')
  // Existing settings resume the unfinished wizard; the language picker is
  // reserved for an instance that has never saved settings.
  await expect(page.locator('.page-intro')).toContainText('连接你的服务')
  await page.getByRole('button', { name: '管理核心', exact: true }).click()
  await expect(page.getByRole('heading', { name: '每个组件，都照顾好。' })).toBeVisible()
  await page.getByRole('button', { name: '返回配置引导', exact: true }).click()
  await expect(page.locator('.core-setup')).toContainText('等待核心就绪')
  await page.evaluate(() => { (window as any).__test.healthReady = true })
  await expect(page.locator('.core-setup')).toContainText('核心已就绪', { timeout: 10000 })
  await expect(page.getByRole('button', { name: '暂不导入，继续', exact: true })).toBeEnabled()
})

test('core management returns to the import dialog and preserves chosen identities', async ({ page }) => {
  await desktop(page)
  await page.locator('.chat-heading').getByRole('button', { name: '导入记录' }).click()
  await page.getByRole('button', { name: '选择文件', exact: true }).click()
  await page.getByRole('group', { name: /^这是我/ }).getByRole('checkbox', { name: /Alice/ }).check()
  await page.getByRole('group', { name: /^这是 TA/ }).getByRole('checkbox', { name: /Bob/ }).check()
  await page.evaluate(() => { (window as any).__test.healthReady = false })
  await page.getByRole('button', { name: '管理核心', exact: true }).click({ timeout: 10000 })
  await page.getByRole('button', { name: '返回导入记录', exact: true }).click()
  await expect(page.locator('.import-dialog')).toBeVisible()
  await expect(page.getByRole('group', { name: /^这是我/ }).getByRole('checkbox', { name: /Alice/ })).toBeChecked()
  await expect(page.getByRole('group', { name: /^这是 TA/ }).getByRole('checkbox', { name: /Bob/ })).toBeChecked()
})

test('a ready core displays ready without an unnecessary restart action', async ({ page }) => {
  await desktop(page)
  await page.locator('.sidebar-bottom').getByRole('button', { name: /组件与更新/ }).click()
  await expect(page.locator('.component-card .pill')).toHaveText('核心已就绪')
  await expect(page.getByRole('button', { name: '重启并应用', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'restart'))).toHaveLength(0)
})

test('saved model changes require restart and return to ready after applying', async ({ page }) => {
  await desktop(page)
  await expect(page.locator('.local-state')).toContainText('核心已就绪')
  await page.locator('.sidebar-bottom').getByRole('button', { name: /设置/ }).click()
  await page.locator('#provider-deepseek .model-select input').fill('changed-main')
  await page.getByRole('button', { name: '保存设置', exact: true }).click()
  await page.locator('.sidebar-bottom').getByRole('button', { name: /组件与更新/ }).click()
  await page.getByRole('button', { name: '重启并应用', exact: true }).click()
  await expect(page.locator('.component-card .pill')).toHaveText('核心已就绪', { timeout: 10000 })
  await expect(page.getByRole('button', { name: '重启并应用', exact: true })).toHaveCount(0)
  const applied = await page.evaluate(() => (window as any).__test.applied)
  expect(applied.providers.deepseek.model).toBe('changed-main')
})

test('identity changes still offer restart until the new identity is applied', async ({ page }) => {
  await desktop(page)
  await expect(page.locator('.local-state')).toContainText('核心已就绪')
  await page.evaluate(() => { (window as any).__test.restartRequired = true })
  await page.locator('.sidebar-bottom').getByRole('button', { name: /组件与更新/ }).click()
  await page.getByRole('button', { name: '重启并应用', exact: true }).click({ timeout: 10000 })
  await expect(page.locator('.component-card .pill')).toHaveText('核心已就绪', { timeout: 10000 })
  await expect(page.getByRole('button', { name: '重启并应用', exact: true })).toHaveCount(0)
})

test('desktop image attachments are prepared, sent and retained with the conversation', async ({ page }) => {
  await desktop(page, false, '/?vision')
  await page.getByRole('button', { name: '添加图片', exact: true }).click()
  await expect(page.locator('.composer-images img')).toBeVisible()
  await expect(page.getByRole('button', { name: '发送消息', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '发送消息', exact: true }).click()
  await expect(page.locator('.message.assistant')).toContainText('Image reply')
  await expect(page.locator('.message-images img')).toBeVisible()
  const sent = await page.evaluate(() => (window as any).__test.calls.find((c: any) => c.method === 'send_chat'))
  expect(sent.args.content).toBe('')
  expect(sent.args.attachments[0].dataUrl).toMatch(/^data:image\/jpeg;base64,/)
  await expect(page.locator('.composer-images img')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/chat-images.png', fullPage: true })
})

test('the current newest conversation can be deleted while the final conversation is protected', async ({ page }) => {
  await desktop(page)
  await page.getByRole('button', { name: '新建会话', exact: true }).click()
  await expect(page.locator('.conversation-entry')).toHaveCount(1)
  await page.getByRole('button', { name: '新建会话', exact: true }).click()
  await expect(page.locator('.conversation-entry')).toHaveCount(2)
  const newest = await page.evaluate(() => (window as any).__test.conversation.id)
  await page.locator('.conversation-entry').first().click({ button: 'right' })
  await page.getByRole('menuitem', { name: '删除本机会话', exact: true }).click()
  await expect(page.locator('.conversation-delete-confirm')).toBeVisible()
  await page.getByRole('button', { name: '删除会话', exact: true }).click()
  await expect(page.locator('.conversation-entry')).toHaveCount(1)
  expect(await page.evaluate(id => (window as any).__test.calls.some((call: any) => call.method === 'delete_conversation' && call.args.id === id), newest)).toBe(true)
  await page.locator('.conversation-entry').first().click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: '删除本机会话', exact: true })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: '删除本机会话', exact: true })).toBeDisabled()
})

test('conversation context menu renames and reorders without switching the active conversation', async ({ page }) => {
  await desktop(page)
  for (let count = 1; count <= 3; count++) {
    await page.getByRole('button', { name: '新建会话', exact: true }).click()
    await expect(page.locator('.conversation-entry')).toHaveCount(count)
  }
  const active = await page.evaluate(() => (window as any).__test.conversation.id)
  await page.locator('.conversation-entry').last().click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: '下移', exact: true })).toBeDisabled()
  await page.getByRole('menuitem', { name: '重命名', exact: true }).click()
  await page.getByRole('textbox', { name: '会话名称', exact: true }).fill('日常聊天')
  await page.getByRole('dialog', { name: '重命名会话', exact: true }).getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('.conversation-entry').last()).toContainText('日常聊天')
  expect(await page.evaluate(() => (window as any).__test.conversation.id)).toBe(active)
  await page.locator('.conversation-entry').last().click({ button: 'right' })
  await page.getByRole('menuitem', { name: '上移', exact: true }).click()
  await expect(page.locator('.conversation-entry').nth(1)).toContainText('日常聊天')
  await page.locator('.conversation-entry').nth(1).click({ button: 'right' })
  await page.getByRole('menuitem', { name: '下移', exact: true }).click()
  await expect(page.locator('.conversation-entry').last()).toContainText('日常聊天')
  await page.locator('.conversation-entry').first().click({ button: 'right' })
  await expect(page.getByRole('menuitem', { name: '上移', exact: true })).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
})

test('analysis report and diagnostics disclosures look like buttons and start collapsed', async ({ page }) => {
  await desktop(page)
  await page.evaluate(() => {
    const state = (window as any).__test
    state.analysisDiagnostics = { prompt_ready: state.analysisArtifacts, state: 'empty', has_reports: true,
      events: 0, observations: 0, available_reports: [], blocks: 0, completed: 0, skipped: 0,
      empty_reports: [], failures: [], directory: 'C:\\AfterglowData\\profiles\\default\\core\\data\\analysis' }
  })
  await page.getByRole('button', { name: '高级功能', exact: true }).click()
  const controls = page.locator('.analysis-disclosure-toggle')
  await expect(controls).toHaveCount(2)
  for (const control of await controls.all()) {
    expect(await control.evaluate(element => ({ border: getComputedStyle(element).borderTopStyle, width: getComputedStyle(element).borderTopWidth, padding: parseFloat(getComputedStyle(element).paddingTop) }))).toEqual({ border: 'solid', width: '1px', padding: 11 })
    await expect(control.locator('svg')).toHaveCount(1)
  }
  await expect(page.locator('.saved-report-details')).not.toHaveAttribute('open')
  await page.getByText('展开已有报告', { exact: true }).click()
  await expect(page.locator('.saved-report-details')).toHaveAttribute('open')
  await page.getByText('分块诊断与本地目录', { exact: true }).click()
  await expect(page.getByRole('button', { name: '打开本地目录', exact: true })).toBeVisible()
})

test('desktop updates explain bundled extensions and require an explicit install action', async ({ page }) => {
  await desktop(page)
  await page.locator('.sidebar-bottom').getByRole('button', { name: /组件与更新/ }).click()
  await expect(page.getByRole('heading', { name: '桌面程序与自带扩展' })).toBeVisible()
  await page.getByRole('button', { name: '更新桌面程序与扩展', exact: true }).click()
  await expect(page.getByText('下载并校验成功后', { exact: false })).toBeVisible()
  await page.setViewportSize({ width: 800, height: 620 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: 'test-results/desktop-update-confirm.png', fullPage: true })
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'apply_desktop_update'))).toBe(false)
  await page.getByRole('button', { name: '下载更新并退出安装', exact: true }).click()
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'apply_desktop_update'))).toBe(true)
})

test('document and nested chat scrollbars use the Afterglow paper palette', async ({ page }) => {
  await desktop(page)
  const colors = await page.evaluate(() => ({
    document: getComputedStyle(document.documentElement).scrollbarColor,
    chat: getComputedStyle(document.querySelector('.messages')!).scrollbarColor,
  }))
  expect(colors.document).toBe('rgb(176, 154, 121) rgb(237, 232, 218)')
  expect(colors.chat).toBe(colors.document)
  await page.locator('.sidebar-bottom').getByRole('button', { name: /设置/ }).click()
  await page.screenshot({ path: 'test-results/settings-paper-scrollbar.png', fullPage: true })
})

test('startup checks repositories in the background and offers an update notice', async ({ page }) => {
  await desktop(page, false, '/?repository-update')
  await expect(page.locator('.repository-update-notice')).toContainText('0.1.0-internal.99')
  expect(await page.evaluate(() => (window as any).__test.calls.some((call: any) => call.method === 'start_update_checks'))).toBe(true)
  await page.locator('.repository-update-notice').getByRole('button', { name: /查看更新/ }).click()
  await expect(page.getByRole('heading', { name: '桌面程序与自带扩展' })).toBeVisible()
})

test('a failed direct GitHub download shows the cause and never launches installation', async ({ page }) => {
  await desktop(page, false, '/?download-fails')
  await page.locator('.sidebar-bottom').getByRole('button', { name: /组件与更新/ }).click()
  await page.getByRole('button', { name: '更新桌面程序与扩展', exact: true }).click()
  await page.getByRole('button', { name: '下载更新并退出安装', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('无法连接 GitHub：连接超时')
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'apply_desktop_update'))).toBe(false)
  await expect(page.getByRole('button', { name: '下载更新并退出安装', exact: true })).toBeEnabled()
})

async function fillRequiredServices(page: Page, fail = false) {
  await page.locator('#provider-deepseek .model-select input').fill('test-main')
  for (const role of ['deepseek', 'embedding', 'zhipu']) {
    const row = page.locator('#provider-' + role)
    await row.locator('.key-input input').fill('fixture-' + role)
    await row.getByRole('button', { name: '保存并测试', exact: true }).click()
    if (fail) {
      await expect(row.locator('.test-result')).toContainText('测试网络不可用')
      await row.getByRole('button', { name: '我确认配置无误，跳过测试并保存', exact: true }).click()
    }
  }
}

test('AI conversion requires explicit identities and passes the selected roles', async ({ page }) => {
  await desktop(page)
  await page.locator('.chat-heading').getByRole('button', { name: '导入记录' }).click()
  await page.getByRole('button', { name: '选择文件', exact: true }).click()
  await page.getByText('查看账号的消息示例', { exact: true }).click()
  await expect(page.getByText('Alice message', { exact: true })).toBeVisible()
  await expect(page.getByText('转换中有 1 / 3 条记录', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '重新分析格式', exact: true }).click()
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'reanalyze_import'))).toBe(true)
  const importButton = page.getByRole('button', { name: '确认身份并导入' })
  const self = page.getByRole('group', { name: /^这是我/ }), other = page.getByRole('group', { name: /^这是 TA/ })
  await expect(self.getByRole('checkbox', { name: /Bob/ })).not.toBeChecked()
  await expect(other.getByRole('checkbox', { name: /Alice/ })).not.toBeChecked()
  await expect(importButton).toBeDisabled()
  await self.getByRole('checkbox', { name: /Bob/ }).check()
  await expect(other.getByRole('checkbox', { name: /Bob/ })).toBeDisabled()
  await other.getByRole('checkbox', { name: /Alice/ }).check()
  await expect(importButton).toBeEnabled()
  await importButton.click()
  const call = await page.evaluate(() => (window as any).__test.calls.find((c: any) => c.method === 'start_import'))
  expect(call.args.selfUids).toEqual(['bob'])
  expect(call.args.friendUids).toEqual(['alice'])
  await expect(page.locator('.pill').filter({ hasText: /^已完成$/ })).toBeVisible()
  await expect(page.getByText('导入完成，核心已就绪，可以继续。', { exact: true })).toBeVisible({ timeout: 10000 })
  await expect(page.getByRole('button', { name: '取消导入', exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => (window as any).__test.calls.filter((item: any) => item.method === 'restart').length)).toBe(1)
  await page.screenshot({ path: 'test-results/import-identity.png', fullPage: true })
  await page.keyboard.press('Escape')
  await expect(page.locator('.import-dialog')).not.toBeVisible()
  await page.locator('.chat-heading').getByRole('button', { name: '导入记录' }).click()
  await expect(page.getByText('导入完成，核心已就绪，可以继续。', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭导入窗口' }).click()
  await page.getByRole('combobox', { name: '切换 Afterglow 实例' }).selectOption('second')
  await page.locator('.chat-heading').getByRole('button', { name: '导入记录' }).click()
  await expect(page.getByText('Alice message', { exact: true })).toHaveCount(0)
})

test('built-in WeChat renders QR locally and supports binding and revocation', async ({ page }) => {
  await desktop(page)
  await page.locator('nav').getByRole('button', { name: '扩展', exact: true }).click()
  const weixin = page.locator('.extension-card').filter({ hasText: '微信' })
  await weixin.getByRole('button', { name: /扫码/ }).click()
  const qr = weixin.locator('.weixin-qr img')
  await expect(qr).toBeVisible()
  await expect(qr).toHaveAttribute('src', /^data:image\/png;base64,/)
  await weixin.getByRole('textbox', { name: '微信验证码' }).fill('567890')
  await weixin.getByRole('button', { name: '提交验证码' }).click()
  await expect(qr).toHaveCount(0)
  await weixin.getByRole('button', { name: '连接', exact: true }).click()
  await expect(weixin.getByText('123456')).toBeVisible()
  await weixin.getByRole('button', { name: /允许|确认|批准/ }).click()
  await expect(weixin.getByText('123456')).toHaveCount(0)
  await weixin.getByRole('button', { name: '解除绑定' }).click()
  await weixin.getByRole('button', { name: /断开/ }).click()
  await page.screenshot({ path: 'test-results/extensions.png', fullPage: true })
})


test('advanced analysis uses confirmed sources and real task progress', async ({ page }) => {
  await desktop(page)
  await page.getByRole('button', { name: '高级分析', exact: true }).click()
  await expect(page.getByText('records.json', { exact: false })).toBeVisible()
  await page.getByRole('button', { name: '开始分析', exact: true }).click()
  await expect(page.getByText('Test analysis complete')).toBeVisible()
  const call = await page.evaluate(() => (window as any).__test.calls.find((c: any) => c.method === 'analysis_start'))
  expect(call.args.files).toEqual(['/uploads/converted.json'])
  expect(call.args.timeline).toBe(true)
  expect(call.args.personality).toBe(true)
})

test('first screen selects language and English has manual empty model fields', async ({ page }) => {
  await desktop(page, true)
  await expect(page.locator('.language-screen')).toBeVisible()
  await page.screenshot({ path: 'test-results/language-screen.png' })
  await page.getByRole('button', { name: 'English en-US' }).click()
  await page.locator('.language-continue').click()
  await expect(page.locator('.preset-grid')).toHaveCount(0)
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('.custom-provider-fields')).toHaveCount(4)
  await expect(page.locator('.channel-trigger strong')).toHaveText(Array(4).fill('Custom OpenAI-compatible API'))
  for (const field of await page.locator('.custom-provider-fields input').all()) await expect(field).toHaveValue('')
  await expect(page.locator('.provider-row input[type="password"]')).toHaveCount(4)
  for (const field of await page.locator('.provider-row input[type="password"]').all()) await expect(field).toHaveValue('')
  await expect(page.locator('.speed-control')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/english-custom-channels.png', fullPage: true })
})

test('window controls use native actions and chat models expose both API protocols', async ({ page }) => {
  await desktop(page)
  await page.locator('.window-controls').getByRole('button', { name: '最小化', exact: true }).click()
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'plugin:window|minimize'))).toBe(true)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  const provider = page.locator('#provider-deepseek')
  const protocolSwitch = provider.locator('.protocol-switch')
  await expect.poll(() => protocolSwitch.evaluate(element => element.getBoundingClientRect().height)).toBeLessThan(36)
  await provider.getByRole('radio', { name: 'Responses /responses' }).click()
  await expect(provider.getByRole('radio', { name: 'Responses /responses' })).toHaveAttribute('aria-checked', 'true')
  await provider.getByRole('button', { name: '保存并测试' }).click()
  const request = await page.evaluate(() => (window as any).__test.calls.find((c: any) => c.method === 'test_provider'))
  expect(request.args.protocol).toBe('responses')
  await page.screenshot({ path: 'test-results/api-protocol-selection.png', fullPage: true })
})

test('closing asks first, cancelling keeps services alive, and minimizing preserves the session', async ({ page }) => {
  await desktop(page)
  const close = page.locator('.window-controls').getByRole('button', { name: '关闭', exact: true })
  const dialog = page.getByRole('dialog', { name: '要如何关闭 Afterglow？' })
  await close.click()
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText('QQ、微信扩展')
  await expect(dialog.getByRole('button', { name: /最小化到托盘/ })).toBeFocused()
  await page.screenshot({ path: 'test-results/window-close-confirm.png' })
  await page.keyboard.press('Escape')
  await expect(dialog).not.toBeVisible()
  await expect(close).toBeFocused()
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => /plugin:window\|(close|destroy)|stop_extension|^stop$/.test(c.method)))).toBe(false)
  await close.click()
  await dialog.getByRole('button', { name: '取消', exact: true }).last().click()
  await expect(dialog).not.toBeVisible()
  await close.click()
  await dialog.getByRole('button', { name: /最小化到托盘/ }).click()
  await expect(dialog).not.toBeVisible()
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'hide_to_tray'))).toBe(true)
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => /plugin:window\|(close|destroy)|stop_extension|^stop$/.test(c.method)))).toBe(false)
})

test('native close requests also ask and only explicit exit shuts down the application', async ({ page }) => {
  await desktop(page)
  await page.evaluate(() => (window as any).__test.emitClose())
  const dialog = page.getByRole('dialog', { name: '要如何关闭 Afterglow？' })
  await expect(dialog).toBeVisible()
  await page.evaluate(() => (window as any).__test.emitClose())
  await expect(page.locator('.window-close-dialog[open]')).toHaveCount(1)
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'exit_application'))).toBe(false)
  await dialog.getByRole('button', { name: /退出程序/ }).click()
  expect(await page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'exit_application').length)).toBe(1)
})

test('close choices recover from a failed native action and fit a small window', async ({ page }) => {
  await desktop(page, false, '/?minimize-fails')
  await page.setViewportSize({ width: 500, height: 420 })
  await page.locator('.window-close').click()
  const dialog = page.getByRole('dialog', { name: '要如何关闭 Afterglow？' })
  await dialog.getByRole('button', { name: /最小化到托盘/ }).click()
  await expect(dialog.getByRole('alert')).toContainText('Window action failed')
  await expect(dialog.getByRole('button', { name: /退出程序/ })).toBeEnabled()
  const bounds = (await dialog.boundingBox())!
  expect(bounds.x).toBeGreaterThanOrEqual(0)
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(500)
  expect(bounds.height).toBeLessThanOrEqual(420)
  await page.screenshot({ path: 'test-results/window-close-small.png' })
})

test('close confirmation follows the selected language from the first screen', async ({ page }) => {
  await desktop(page, true)
  await page.getByRole('button', { name: 'English en-US' }).click()
  await page.locator('.window-close').click()
  const dialog = page.getByRole('dialog', { name: 'How would you like to close Afterglow?' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Minimize to tray/ })).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Exit application/ })).toBeVisible()
  await expect.poll(() => page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'set_desktop_preferences' && c.args.locale === 'en-US'))).toBe(true)
})

test('remembered tray behavior survives reopening and can be reset in settings', async ({ page }) => {
  await desktop(page)
  const dialog = page.getByRole('dialog', { name: '要如何关闭 Afterglow？' })
  await page.locator('.window-close').click()
  await dialog.getByRole('checkbox', { name: /以后不再询问/ }).check()
  await dialog.getByRole('button', { name: /最小化到托盘/ }).click()
  await expect(dialog).not.toBeVisible()
  await page.evaluate(() => (window as any).__test.emitClose())
  await expect.poll(() => page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'hide_to_tray').length)).toBe(2)
  await expect(dialog).not.toBeVisible()
  await page.reload()
  await page.locator('.window-close').click()
  await expect.poll(() => page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'hide_to_tray').length)).toBe(1)
  await expect(dialog).not.toBeVisible()
  await page.getByRole('button', { name: '设置', exact: true }).click()
  const preferences = page.getByRole('region', { name: '启动与关闭' })
  await expect(preferences.getByRole('radio', { name: /最小化到托盘/ })).toHaveAttribute('aria-checked', 'true')
  await preferences.getByRole('radio', { name: /每次询问/ }).click()
  await expect(preferences.getByRole('radio', { name: /每次询问/ })).toHaveAttribute('aria-checked', 'true')
  await page.locator('.window-close').click()
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('checkbox', { name: /以后不再询问/ })).not.toBeChecked()
})

test('startup is opt-in and desktop choices save without model configuration changes', async ({ page }) => {
  await desktop(page)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  const preferences = page.getByRole('region', { name: '启动与关闭' })
  const startup = preferences.getByRole('switch', { name: '开机自启动' })
  await expect(startup).toHaveAttribute('aria-checked', 'false')
  const savedModels = await page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'save_settings').length)
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'set_desktop_preferences' && c.args.autostart !== undefined))).toBe(false)
  await startup.click()
  await expect(startup).toHaveAttribute('aria-checked', 'true')
  await startup.click()
  await expect(startup).toHaveAttribute('aria-checked', 'false')
  await preferences.getByRole('radio', { name: /退出程序/ }).click()
  await expect(preferences.getByRole('radio', { name: /退出程序/ })).toHaveAttribute('aria-checked', 'true')
  await page.locator('.window-close').click()
  await expect.poll(() => page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'exit_application').length)).toBe(1)
  await expect(page.locator('.window-close-dialog')).not.toBeVisible()
  expect(await page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'save_settings').length)).toBe(savedModels)
  await page.screenshot({ path: 'test-results/desktop-preferences.png', fullPage: true })
})

test('failed preference persistence keeps the window open and the choice unchanged', async ({ page }) => {
  await desktop(page, false, '/?preference-fails')
  await page.locator('.window-close').click()
  const dialog = page.getByRole('dialog', { name: '要如何关闭 Afterglow？' })
  await dialog.getByRole('checkbox', { name: /以后不再询问/ }).check()
  await dialog.getByRole('button', { name: /最小化到托盘/ }).click()
  await expect(dialog.getByRole('alert')).toContainText('Preference save failed')
  expect(await page.evaluate(() => (window as any).__test.calls.some((c: any) => c.method === 'hide_to_tray'))).toBe(false)
  expect(await page.evaluate(() => (window as any).__test.preferences.closeAction)).toBe('ask')
  await dialog.getByRole('button', { name: '取消', exact: true }).last().click()
  await page.locator('.window-close').click()
  await expect(dialog.getByRole('alert')).toHaveCount(0)
})

test('unavailable tray keeps closing recoverable', async ({ page }) => {
  await desktop(page, false, '/?no-tray')
  await page.locator('.window-close').click()
  const dialog = page.getByRole('dialog', { name: '要如何关闭 Afterglow？' })
  await expect(dialog.getByRole('button', { name: /最小化到托盘/ })).toBeDisabled()
  await dialog.getByRole('button', { name: /退出程序/ }).click()
  await expect.poll(() => page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'exit_application').length)).toBe(1)
})

test('onboarding prepares the bundled core without leaving the import step', async ({ page }) => {
  await desktop(page, true)
  await page.goto('/?first-run&needs-core')
  await page.locator('.language-continue').click()
  await page.screenshot({ path: 'test-results/onboarding-preset.png' })
  await page.locator('.setup-footer').getByRole('button').last().click()
  await fillRequiredServices(page)
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('.optional-services')).toBeVisible()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await page.getByRole('button', { name: '准备核心', exact: true }).click()
  await expect(page.locator('.core-setup')).toContainText('核心已就绪')
  await expect(page.locator('.import-records')).toBeVisible()
  const calls = await page.evaluate(() => (window as any).__test.calls.map((call: any) => call.method))
  expect(calls.indexOf('save_settings')).toBeLessThan(calls.indexOf('install'))
  expect(calls.indexOf('install')).toBeLessThan(calls.indexOf('start'))
  await page.screenshot({ path: 'test-results/onboarding-import.png', fullPage: true })
})


test('model roles are generic and API channels are keyboard accessible', async ({ page }) => {
  await desktop(page)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  const providers = page.locator('.provider-row')
  await expect(providers.nth(0).getByRole('heading', { level: 3 })).toContainText('大模型')
  await expect(providers.nth(3).getByRole('heading', { level: 3 })).toContainText('小模型')
  await expect(page.locator('nav').getByRole('button', { name: '导入记录' })).toHaveCount(0)
  const channel = page.getByRole('combobox', { name: '大模型 · API 渠道', exact: true })
  await channel.focus()
  await channel.press('ArrowDown')
  await expect(channel).toHaveAttribute('aria-expanded', 'true')
  await channel.press('End')
  await channel.press('Enter')
  await expect(channel).toHaveAttribute('aria-expanded', 'false')
  await expect(channel).toContainText('自定义')
  await expect(providers.nth(0).getByRole('button', { name: '获取密钥' })).toHaveCount(0)
  await expect(providers.nth(0).locator('.custom-provider-fields')).toBeVisible()
  await providers.nth(0).locator('.custom-provider-fields input').nth(0).fill('https://my-provider.example/v1')
  await providers.nth(0).locator('.custom-provider-fields input').nth(1).fill('my-chat-model')
  await page.getByRole('radio', { name: /均衡/ }).click()
  await expect(channel).toContainText('自定义')
  await expect(providers.nth(0).locator('.custom-provider-fields input').nth(0)).toHaveValue('https://my-provider.example/v1')
  await channel.click()
  await expect(page.locator('.channel-options')).toHaveCSS('opacity', '1')
  await page.screenshot({ path: 'test-results/model-channels.png' })
  await page.keyboard.press('Escape')
  await expect(channel).toHaveAttribute('aria-expanded', 'false')
  await page.getByRole('button', { name: '获取嵌入密钥' }).click()
  await page.getByRole('button', { name: '获取重排密钥' }).click()
  const urls = await page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'open_external').map((c: any) => c.args.url))
  expect(urls).toEqual(['https://maas.xfyun.cn/modelSquare/base/2529035470232577', 'https://maas.xfyun.cn/modelSquare/base/2529035707210755'])
  await channel.click()
  await page.getByRole('option', { name: /智谱 GLM API/ }).click()
  await expect(providers.nth(0).locator('.model-select input')).toHaveValue('glm-4-flash')
  await providers.nth(0).getByRole('button', { name: '获取密钥' }).click()
  const smallChannel = page.getByRole('combobox', { name: '小模型 · API 渠道', exact: true })
  await smallChannel.click()
  await page.getByRole('option', { name: /DeepSeek API/ }).click()
  await expect(providers.nth(3).locator('.model-select input')).toHaveValue('deepseek-v4-pro')
  await channel.click()
  await page.getByRole('option', { name: /自定义/ }).click()
  await expect(providers.nth(0).locator('.custom-provider-fields input').nth(0)).toHaveValue('https://my-provider.example/v1')
  await expect(providers.nth(0).locator('.custom-provider-fields input').nth(1)).toHaveValue('my-chat-model')
  const selectedUrl = await page.evaluate(() => (window as any).__test.calls.filter((c: any) => c.method === 'open_external').at(-1).args.url)
  expect(selectedUrl).toBe('https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys')
})

test('import dialog respects reduced motion and restores keyboard focus', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await desktop(page)
  const trigger = page.locator('.chat-heading').getByRole('button', { name: '导入记录' })
  await trigger.click()
  await expect(page.locator('.import-dialog')).toBeVisible()
  await expect(page.getByRole('button', { name: '关闭导入窗口' })).toBeFocused()
  expect(await page.locator('.import-dialog').evaluate(el => getComputedStyle(el).animationName)).toBe('none')
  await page.keyboard.press('Escape')
  await expect(page.locator('.import-dialog')).not.toBeVisible()
  await expect(trigger).toBeFocused()
})

test('minimum desktop size keeps setup and chat within the window', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 620 })
  await desktop(page)
  for (const name of ['设置', '聊天']) {
    await page.getByRole('button', { name, exact: true }).click()
    if (name === '聊天') await expect(page.locator('.page-flow')).toHaveCount(0)
    else await expect(page.locator('.service-section')).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  }
  await page.screenshot({ path: 'test-results/chat-small-window.png' })
  await page.locator('.chat-heading').getByRole('button', { name: '导入记录' }).click()
  await expect(page.locator('.import-dialog')).toBeVisible()
  const bounds = await page.locator('.import-dialog').boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(800)
  expect(bounds!.height).toBeLessThanOrEqual(620)
})


test('first-run blocks empty settings and only skips failed verification with complete fields', async ({ page }) => {
  await desktop(page, true)
  await page.goto('/?first-run&failed-tests&needs-core')
  await page.locator('.language-continue').click()
  await expect(page.locator('nav').getByRole('button', { name: '聊天', exact: true })).toBeDisabled()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await page.locator('#provider-deepseek .model-select input').fill('')
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('#provider-deepseek .field-error')).toContainText('请填写模型名称')
  await expect(page.locator('.optional-services')).toHaveCount(0)
  await fillRequiredServices(page, true)
  const first = page.locator('#provider-deepseek')
  await first.locator('.model-select input').fill('')
  await first.getByRole('button', { name: '保存并测试', exact: true }).click()
  await first.getByRole('button', { name: '我确认配置无误，跳过测试并保存', exact: true }).click()
  await expect(first.locator('.field-error')).toContainText('请填写模型名称')
  await first.locator('.model-select input').fill('test-main')
  await first.getByRole('button', { name: '保存并测试', exact: true }).click()
  await first.getByRole('button', { name: '我确认配置无误，跳过测试并保存', exact: true }).click()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('.optional-services')).toBeVisible()
  await page.getByRole('radio', { name: /单独配置识图模型/ }).check()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('#provider-vision .field-error')).toContainText('请填写模型名称')
  await page.getByRole('radio', { name: /暂不开启/ }).check()
  await page.screenshot({ path: 'test-results/onboarding-optional-services.png', fullPage: true })
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('.setup-footer').getByRole('button').last()).toBeDisabled()
  await page.getByRole('button', { name: '准备核心', exact: true }).click()
  await page.getByRole('button', { name: '暂不导入，继续', exact: true }).click()
  await page.getByRole('button', { name: '开始聊天', exact: true }).click()
  await expect(page.locator('.chat-heading')).toBeVisible()
  const saved = await page.evaluate(() => (window as any).__test.settings)
  expect(saved.configured).toBe(true)
  expect(saved.providers.deepseek.verification).toBe('skipped')
  expect(saved.services.vision).toBe('off')
  await page.reload()
  await expect(page.locator('.chat-heading')).toBeVisible()
  await expect(page.locator('.language-screen')).toHaveCount(0)
})

test('web setup offers supported protocols and only SearXNG permits an empty key', async ({ page }) => {
  await desktop(page, true)
  await page.locator('.language-continue').click()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await fillRequiredServices(page)
  await page.locator('.setup-footer').getByRole('button').last().click()
  await page.getByRole('switch', { name: '联网搜索', exact: true }).click()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('#provider-search .field-error')).toContainText('API 密钥')
  const channel = page.getByRole('combobox', { name: '联网搜索 · API 渠道', exact: true })
  await channel.click()
  await page.getByRole('option', { name: /SearXNG/ }).click()
  await page.locator('#provider-search input[type="url"]').fill('https://search.example')
  await page.locator('#provider-search').getByRole('button', { name: '保存并测试', exact: true }).click()
  await page.locator('.setup-footer').getByRole('button').last().click()
  await expect(page.locator('.core-setup')).toBeVisible()
  const settings = await page.evaluate(() => (window as any).__test.settings)
  expect(settings.services.webSearch).toBe(true)
  expect(settings.providers.search.channel).toBe('searxng')
  expect(settings.providers.search.baseUrl).toBe('https://search.example')
})

test('debug mode applies through Settings and provides scoped original-core diagnostics', async ({ page }) => {
  await desktop(page)
  await expect(page.locator('.chat-heading')).toBeVisible()
  await expect(page.locator('.chat-heading').getByRole('button', { name: '打开调试面板' })).toHaveCount(0)
  await page.locator('.sidebar-bottom').getByRole('button', { name: '设置', exact: true }).click()
  const preferences = page.getByRole('region', { name: '调试模式', exact: true })
  await preferences.getByRole('switch', { name: '启用 Debug UI 与调试端点', exact: true }).click()
  await expect(preferences.getByRole('switch', { name: '记录完整模型请求与回复', exact: true })).toHaveAttribute('aria-checked', 'false')
  await preferences.getByRole('button', { name: '重启并应用', exact: true }).click()
  await expect(preferences.getByRole('button', { name: '打开调试面板', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByRole('button', { name: '新建会话', exact: true }).click()
  await page.locator('.chat-heading').getByRole('button', { name: '打开调试面板', exact: true }).click()
  const drawer = page.getByRole('dialog', { name: '看看 Afterglow 如何运行' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('42', { exact: true })).toBeVisible()
  await drawer.getByRole('button', { name: '记忆检索', exact: true }).click()
  await drawer.getByLabel('检索文字', { exact: true }).fill('query')
  await drawer.getByRole('button', { name: '运行检索', exact: true }).click()
  await expect(drawer.getByText('Retrieval fixture', { exact: true })).toBeVisible()
  const calls = await page.evaluate(() => (window as any).__test.calls)
  expect(calls.find((item: any) => item.method === 'debug_search').args.conversationId).toBe('6af21773-30ed-447c-ab59-e8a2d820b981')
  expect(calls.some((item: any) => item.method === 'debug_proactive')).toBe(false)
  await drawer.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(drawer).toHaveCount(0)
  await page.locator('.sidebar-bottom').getByRole('button', { name: '设置', exact: true }).click()
  await preferences.getByRole('switch', { name: '启用 Debug UI 与调试端点', exact: true }).click()
  await preferences.getByRole('button', { name: '重启并应用', exact: true }).click()
  await expect(preferences.getByRole('button', { name: '打开调试面板', exact: true })).toBeDisabled()
  const saved = await page.evaluate(() => (window as any).__test.settings.debug)
  expect(saved).toEqual({ enabled: false, fullPayloads: false })
})

test('analysis prompt switches require their corresponding artifacts', async ({ page }) => {
  await desktop(page)
  await page.getByRole('button', { name: '高级分析', exact: true }).click()
  const personality = page.getByRole('switch', { name: '聊天参考人物与关系观察', exact: true })
  const life = page.getByRole('switch', { name: '生活决策参考作息与习惯', exact: true })
  await expect(personality).toBeDisabled()
  await expect(life).toBeDisabled()
  await page.evaluate(() => { (window as any).__test.analysisArtifacts.personalityPrompt = true })
  await page.getByRole('button', { name: '聊天', exact: true }).click()
  await page.getByRole('button', { name: '高级分析', exact: true }).click()
  await expect(personality).toBeEnabled()
  await expect(life).toBeDisabled()
  await personality.click()
  await expect(personality).toHaveAttribute('aria-checked', 'true')
  await page.getByRole('button', { name: '保存使用偏好', exact: true }).click()
  expect(await page.evaluate(() => (window as any).__test.settings.analysis)).toEqual({ personalityPrompt: true, lifeContext: false })
})

test('composer tools align and the sticker description uses the theme surface', async ({ page }) => {
  await desktop(page)
  const image = await page.getByRole('button', { name: '添加图片', exact: true }).boundingBox()
  const sticker = await page.locator('.composer').getByRole('button', { name: '选择表情包', exact: true }).boundingBox()
  expect(image).not.toBeNull()
  expect(sticker).not.toBeNull()
  expect(Math.abs(image!.y - sticker!.y)).toBeLessThan(1)
  expect(image!.height).toBe(sticker!.height)
  await page.getByRole('button', { name: '高级分析', exact: true }).click()
  await expect(page.locator('.sticker-library textarea')).toBeEnabled()
  const colors = await page.locator('.sticker-library').evaluate(element => ({
    description: getComputedStyle(element.querySelector('textarea')!).backgroundColor,
  }))
  expect(colors.description).toBe('rgb(251, 248, 239)')
  expect(colors.description).not.toBe('rgb(255, 255, 255)')
})

test('a late old analysis poll cannot replace a new task or show its old empty report', async ({ page }) => {
  await desktop(page)
  await page.evaluate(() => {
    const state = (window as any).__test
    state.analysisTask = { task_id: 'old', status: 'done', progress: 1, stage: 'Old task' }
    state.analysisDiagnostics = { prompt_ready: state.analysisArtifacts, state: 'empty', has_reports: true,
      events: 0, observations: 0, available_reports: [], blocks: 4, completed: 4, skipped: 4,
      empty_reports: ['timeline', 'personality'], failures: [], directory: 'C:\\analysis' }
  })
  await page.getByRole('button', { name: '高级分析', exact: true }).click()
  await expect(page.getByRole('heading', { name: '结果与诊断' })).toBeVisible()
  await page.evaluate(() => { (window as any).__test.analysisHoldStatus = true })
  await page.getByRole('button', { name: '刷新状态', exact: true }).click()
  await expect.poll(() => page.evaluate(() => (window as any).__test.analysisPendingStatus.some((item: any) => item.id === 'old'))).toBe(true)
  await page.getByRole('button', { name: '开始分析', exact: true }).click()
  await expect(page.getByText('New task pending', { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '结果与诊断' })).toHaveCount(0)
  await page.evaluate(() => {
    const pending = (window as any).__test.analysisPendingStatus
    pending.find((item: any) => item.id === 'old').resolve({ task_id: 'old', status: 'done', progress: 1, stage: 'OLD_POLL_RESULT' })
  })
  await expect(page.getByText('New task pending', { exact: true })).toBeVisible()
  await expect(page.getByText('OLD_POLL_RESULT', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '结果与诊断' })).toHaveCount(0)
})

test('settings offer an optional dedicated historical image model with independent key', async ({ page }) => {
  await desktop(page)
  await page.getByRole('button', { name: '设置', exact: true }).click()
  await expect(page.locator('#provider-imageImportVision')).toHaveCount(0)
  await page.getByRole('switch', { name: '图片导入专用识图模型', exact: true }).click()
  const provider = page.locator('#provider-imageImportVision')
  await expect(provider).toBeVisible()
  const fields = provider.locator('.custom-provider-fields input')
  await expect(fields.nth(0)).toHaveValue('')
  await expect(fields.nth(1)).toHaveValue('')
  await fields.nth(0).fill('https://history.example/v1')
  await fields.nth(1).fill('history-vision')
  await provider.locator('.key-input input').fill('history-test-key')
  await provider.getByRole('button', { name: '保存并测试', exact: true }).click()
  await expect.poll(() => page.evaluate(() => (window as any).__test.calls.some((call: any) => call.method === 'test_provider' && call.args.provider === 'imageImportVision' && call.args.model === 'history-vision'))).toBe(true)
  const key = await page.evaluate(() => (window as any).__test.calls.find((call: any) => call.method === 'set_secret' && call.args.name === 'imageImportVision'))
  expect(key.args.profile.baseUrl).toBe('https://history.example/v1')
  await expect(page.locator('.vision-choice').filter({ has: page.getByRole('radio', { name: /暂不开启/ }) })).toHaveClass(/selected/)
})
