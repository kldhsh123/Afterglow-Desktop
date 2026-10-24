<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import QRCode from 'qrcode'
import { Check, ExternalLink, LoaderCircle, Play, QrCode, RefreshCw, ShieldCheck, Square, Trash2, X } from 'lucide-vue-next'
import { t } from '../i18n'
import { isDesktop, openExternal, rpc, type ExtensionInfo, type Result } from '../services/desktop'

const props = defineProps<{ instanceId: string; ready: boolean }>()
const emit = defineEmits<{ error: [message: string]; busy: [value: boolean] }>()
const items = ref<ExtensionInfo[]>([])
const busy = ref('')
const notice = ref('')
const appId = ref('')
const secret = ref('')
const verifyCode = ref('')
const qrImage = ref('')
const lastQR = ref('')
const log = ref('')
const confirmForget = ref(false)
let active = true
let timer: ReturnType<typeof setTimeout> | undefined
const loginStates = new Set(['login', 'scanned', 'verify'])
const stateLabels = {
  stopped: 'extensions.state.stopped', connecting: 'extensions.state.connecting', connected: 'extensions.state.connected',
  reconnecting: 'extensions.state.reconnecting', login: 'extensions.state.login', scanned: 'extensions.state.scanned',
  verify: 'extensions.state.verify', expired: 'extensions.state.expired', error: 'extensions.state.error', authenticated: 'extensions.state.authenticated',
} as const
function stateLabel(state: string) { return t(stateLabels[state as keyof typeof stateLabels] ?? 'extensions.state.error') }
const weixin = computed(() => items.value.find(item => item.id === 'weixin'))
function call<T>(method: string, args: Record<string, unknown> = {}) {
  return rpc<T>(method, { ...args, instanceId: props.instanceId })
}
async function refresh() {
  const result = await call<{ extensions: ExtensionInfo[] }>('extension_status')
  if (!active) return
  items.value = result.extensions
  const value = weixin.value?.qrContent ?? ''
  if (value !== lastQR.value) {
    lastQR.value = value
    qrImage.value = value ? await QRCode.toDataURL(value, { width: 240, margin: 2, errorCorrectionLevel: 'M' }) : ''
  }
}
async function poll() {
  try { await refresh() } catch (error) { if (active) emit('error', String(error)) }
  if (active && isDesktop) timer = setTimeout(poll, 3000)
}
async function run(name: string, task: () => Promise<Result>) {
  if (busy.value) return
  busy.value = name
  emit('busy', true)
  try {
    const result = await task()
    notice.value = result.message
    await refresh()
  } catch (error) { emit('error', error instanceof Error ? error.message : String(error)) }
  finally { busy.value = ''; emit('busy', false) }
}
async function saveQQ() {
  await run('qq-save', () => call<Result>('save_extension_settings', { id: 'qq', settings: { enabled: true, appId: appId.value.trim(), clientSecret: secret.value.trim() } }))
  secret.value = ''
}
async function toggle(item: ExtensionInfo) {
  await run(item.id, () => call<Result>(item.running ? 'stop_extension' : 'start_extension', { id: item.id }))
}
async function contact(id: string, uid: string, code: string, revoke = false) {
  await run('contact', () => call<Result>('authorize_contact', { id, uid, code, revoke }))
}
async function login() {
  if (weixin.value?.running) await run('weixin-stop', () => call<Result>('stop_extension', { id: 'weixin' }))
  await run('login', () => call<Result>('start_weixin_login'))
}
async function submitCode() {
  await run('verify', () => call<Result>('submit_weixin_verify_code', { code: verifyCode.value.trim() }))
  verifyCode.value = ''
}
async function viewLog(id: string) {
  try { log.value = (await call<{ text: string }>('logs', { id })).text } catch (error) { emit('error', String(error)) }
}
async function forget() {
  await run('forget', () => call<Result>('forget_weixin_login'))
  confirmForget.value = false
}
onMounted(() => { void poll() })
onUnmounted(() => { active = false; clearTimeout(timer); secret.value = ''; verifyCode.value = '' })
</script>

<template>
  <div class="page-intro"><span class="eyebrow">{{ t('ui.continue_the_conversation_elsewhere') }}</span><h1>{{ t('ui.bring_companionship_to_everyday_chat') }}</h1><p>{{ t('ui.builtin_channels_share_this_afterglow_core_and_instance') }}</p></div>
  <p v-if="notice" class="inline-notice" role="status">{{ notice }}</p>
  <article v-for="item in items" :key="item.id" class="surface extension-card">
    <div class="section-heading"><div><h2>{{ item.id === 'qq' ? t('ui.qq_builtin_channel') : t('ui.wechat_builtin_channel') }}</h2><p>{{ item.id === 'qq' ? t('ui.qq_bot_uses_official_qq_bot_platform_credentials') : t('ui.wechat_uses_qr_login_and_keeps_login_state_local') }}</p></div><span class="pill" :class="{ success: item.state === 'connected' }" role="status">{{ stateLabel(item.state) }}</span></div>
    <p v-if="item.error" class="danger-text" role="alert">{{ item.error }}</p>
    <form v-if="item.id === 'qq'" @submit.prevent="saveQQ">
      <div class="form-grid"><label>{{ t('ui.qq_bot_app_id') }}<input v-model="appId" inputmode="numeric" maxlength="40" autocomplete="off" :placeholder="item.credentialsReady ? t('ui.saved_leave_blank_to_keep') : t('ui.enter_app_id')" :disabled="!isDesktop || item.running"/></label><label>{{ t('ui.qq_bot_client_secret') }}<input v-model="secret" type="password" maxlength="4096" autocomplete="new-password" :placeholder="item.credentialsReady ? t('ui.saved_leave_blank_to_keep') : t('ui.enter_client_secret')" :disabled="!isDesktop || item.running"/></label></div>
      <div class="component-actions"><button class="button secondary" type="submit" :disabled="!!busy || !isDesktop || item.running"><Check :size="14"/>{{ t('ui.save_qq_settings') }}</button><button class="text-button" type="button" @click="openExternal('https://q.qq.com/')">{{ t('extensions.qq_console') }}<ExternalLink :size="13"/></button></div>
    </form>
    <div v-if="item.id === 'weixin'" class="extension-login">
      <div v-if="qrImage && loginStates.has(item.state)" class="weixin-qr"><img :src="qrImage" :alt="t('ui.scan_this_qr_code_with_wechat')"/><p>{{ t('ui.scan_this_qr_code_with_wechat') }}</p></div>
      <form v-if="item.verifyCodeRequired" class="form-grid" @submit.prevent="submitCode"><label>{{ t('ui.wechat_verification_code') }}<input v-model="verifyCode" inputmode="numeric" autocomplete="one-time-code" maxlength="16" :placeholder="t('ui.enter_the_code_shown_in_wechat')"/></label><button class="button secondary" type="submit" :disabled="!!busy || !verifyCode.trim()">{{ t('ui.submit_verification_code') }}</button></form>
      <div class="component-actions"><button class="button secondary" :disabled="!!busy || !isDesktop || (item.running && loginStates.has(item.state)) || item.state === 'connected'" @click="login"><QrCode :size="14"/>{{ item.credentialsReady ? t('extensions.login_again') : t('ui.scan_wechat_qr_code') }}</button><button v-if="item.credentialsReady" class="text-button" :disabled="!!busy" @click="confirmForget = true">{{ t('extensions.forget_login') }}</button></div>
    </div>
    <section v-if="item.pendingUsers?.length" class="binding-list"><h3>{{ t('extensions.pending_contacts') }}</h3><p>{{ t('extensions.check_code_notice') }}</p><div v-for="user in item.pendingUsers" :key="user.uid" class="binding-row"><div><strong>{{ t('ui.binding_code') }} {{ user.code }}</strong><small>{{ user.uid }}</small></div><button class="button secondary" :disabled="!!busy || !isDesktop" @click="contact(item.id, user.uid, user.code)">{{ t('ui.confirm_bind_this_user') }}</button><button class="text-button" :disabled="!!busy || !isDesktop" @click="contact(item.id, user.uid, '', true)">{{ t('extensions.reject') }}</button></div></section>
    <section v-if="item.contacts?.length" class="binding-list"><h3>{{ t('extensions.authorized_contacts') }}</h3><div v-for="user in item.contacts" :key="user.uid" class="binding-row"><div><strong>{{ user.name || user.uid }}</strong></div><button class="text-button" :disabled="!!busy || !isDesktop" @click="contact(item.id, user.uid, '', true)"><Trash2 :size="13"/>{{ t('extensions.revoke') }}</button></div></section>
    <p v-if="!ready && !loginStates.has(item.state)" class="muted">{{ t('host.start_the_afterglow_core_before_connecting_a_channel') }}</p>
    <div class="component-actions"><button v-if="item.credentialsReady || item.running" class="button primary" :disabled="!!busy || !isDesktop || (!item.running && !ready)" @click="toggle(item)"><LoaderCircle v-if="busy === item.id" :size="14" class="spinning"/><Square v-else-if="item.running" :size="14"/><Play v-else :size="14"/>{{ item.running ? t('ui.disconnect') : t('ui.connect') }}</button><button class="text-button" :disabled="!!busy || !isDesktop" @click="viewLog(item.id)">{{ t('ui.logs') }}</button></div>
    <small class="muted">{{ item.id === 'qq' ? t('ui.qq_requires_a_qq_open_platform_bot_account') : t('ui.channel_data_and_login_state_are_isolated_per_instance') }}</small>
  </article>
  <div class="note-line"><ShieldCheck :size="16"/><span>{{ t('ui.extensions_are_bundled_with_the_desktop_app_and_need_no_separate_install') }}</span></div>
  <div v-if="confirmForget" class="modal-backdrop" @click.self="confirmForget = false"><section class="instance-dialog" role="dialog" aria-modal="true"><h2>{{ t('extensions.forget_login') }}</h2><p>{{ t('extensions.forget_notice') }}</p><div class="dialog-actions"><button class="button secondary" @click="confirmForget = false">{{ t('common.cancel') }}</button><button class="button primary" :disabled="!!busy" @click="forget">{{ t('extensions.forget_login') }}</button></div></section></div>
  <div v-if="log" class="modal-backdrop" @click.self="log = ''"><section class="log-modal" role="dialog" aria-modal="true" :aria-label="t('ui.logs')"><div class="section-heading"><h2>{{ t('ui.logs') }}</h2><button class="icon-button" :aria-label="t('common.cancel')" @click="log = ''"><X :size="20"/></button></div><pre>{{ log }}</pre></section></div>
</template>
