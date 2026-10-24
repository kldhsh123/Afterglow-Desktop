<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, ArrowRight, Bug, Check, ChevronRight, Ellipsis, ImagePlus, LoaderCircle, MessageCircle, Pencil, Plus, RefreshCw, Send, SmilePlus, SlidersHorizontal, Trash2, Upload, X } from 'lucide-vue-next'
import { locale, t } from '../i18n'
import { chooseImages, isDesktop, rpc } from '../services/desktop'
import { prepareChatImage, type ChatImage } from '../services/chat-images'
import { type Sticker } from '../services/stickers'
import StickerImage from './StickerImage.vue'
import ChatContent from './ChatContent.vue'

const props = defineProps<{ instanceId: string; ready: boolean; selfName: string; friendName: string; presetLabel: string; humanDelay: boolean; visionEnabled: boolean; debugEnabled: boolean }>()
const emit = defineEmits<{ error: [message: string]; busy: [value: boolean]; settings: []; setup: []; import: []; debug: [context: { conversationId?: string; query: string }] }>()
interface Summary { id: string; title: string; updated_at: number }
interface Turn { id: string; content: string; attachments?: ChatImage[]; reply: string | null; state: 'pending' | 'completed' | 'failed'; error: string; created_at: number }
interface Conversation extends Summary { turns: Turn[] }
const conversations = ref<Summary[]>([])
const conversation = ref<Conversation | null>(null)
const input = ref('')
const stickerPicker = ref(false), stickerLoading = ref(false), availableStickers = ref<Sticker[]>([])
const composerInput = ref<HTMLTextAreaElement | null>(null)
const attachments = ref<ChatImage[]>([])
const readingImages = ref(false)
const sending = ref(false)
const loading = ref(false)
const error = ref('')
const pendingDeleteId = ref<string | null>(null)
const contextMenu = ref<{ id: string; x: number; y: number } | null>(null)
const menuElement = ref<HTMLElement | null>(null)
const renameId = ref<string | null>(null), renameTitle = ref('')
const renameInput = ref<HTMLInputElement | null>(null)
const deleteCancel = ref<HTMLButtonElement | null>(null)
const canDeleteConversation = computed(() => conversations.value.length > 1)
const contextIndex = computed(() => conversations.value.findIndex(item => item.id === contextMenu.value?.id))
let menuTrigger: HTMLElement | null = null
const messagesElement = ref<HTMLElement | null>(null)
const lastSeconds = ref<number | null>(null)
const drafts = new Map<string, { text: string; images: ChatImage[] }>()
let alive = true
const canSend = computed(() => props.ready && !sending.value && !loading.value && !readingImages.value && (!!input.value.trim() || !!attachments.value.length))
async function attachPaths(paths: string[]) {
  if (readingImages.value || sending.value || loading.value || !props.ready) return
  if (!props.visionEnabled) { report(new Error(t('chat.image_enable'))); return }
  if (paths.length + attachments.value.length > 4) { report(new Error(t('chat.image_limit'))); return }
  readingImages.value = true
  try {
    const result = await call<{ images: { name: string; dataUrl: string }[] }>('read_chat_images', { paths })
    const prepared = []
    for (const source of result.images) prepared.push(await prepareChatImage(source.name, source.dataUrl))
    if (alive) attachments.value.push(...prepared)
  } catch (e) { report(e) } finally { readingImages.value = false }
}
async function pickSticker() {
  if (!props.ready || sending.value || loading.value) return
  stickerPicker.value = !stickerPicker.value
  if (!stickerPicker.value) return
  stickerLoading.value = true
  try { const result = await call<{ items: Sticker[] }>('stickers_list', { owner: 'self' }); if (alive) availableStickers.value = result.items }
  catch (error) { if (alive) report(error) }
  finally { stickerLoading.value = false }
}
async function insertSticker(sticker: Sticker) {
  const text = '[sticker:' + sticker.name + ']'
  if (input.value.length + text.length + 1 > 16000) return
  input.value += (input.value && !/\s$/.test(input.value) ? ' ' : '') + text
  stickerPicker.value = false
  await nextTick(); composerInput.value?.focus()
}
async function pickImages() { try { const paths = await chooseImages(); if (paths.length) await attachPaths(paths) } catch (e) { report(e) } }
defineExpose({ attachPaths })
function call<T>(method: string, args: Record<string, unknown> = {}) { return rpc<T>(method, { ...args, instanceId: props.instanceId }) }
function report(e: unknown) { error.value = e instanceof Error ? e.message : String(e); emit('error', error.value) }
async function scrollToBottom() { await nextTick(); messagesElement.value?.scrollTo({ top: messagesElement.value.scrollHeight, behavior: 'auto' }) }
async function refreshList() { const result = await call<{ conversations: Summary[] }>('list_conversations'); if (alive) conversations.value = result.conversations }
async function openConversation(id: string) {
  if (sending.value || loading.value || readingImages.value) return
  loading.value = true
  error.value = ''
  closeConversationMenu()
  pendingDeleteId.value = null
  if (conversation.value) drafts.set(conversation.value.id, { text: input.value, images: attachments.value })
  try { const result = await call<Conversation>('get_conversation', { id }); if (alive) { conversation.value = result; input.value = drafts.get(id)?.text ?? ''; attachments.value = drafts.get(id)?.images ?? []; lastSeconds.value = null; await scrollToBottom() } } catch (e) { report(e) } finally { loading.value = false }
}
async function newConversation() {
  if (!isDesktop || sending.value || loading.value || readingImages.value) return
  loading.value = true
  error.value = ''
  closeConversationMenu()
  pendingDeleteId.value = null
  if (conversation.value) drafts.set(conversation.value.id, { text: input.value, images: attachments.value })
  try { const result = await call<Conversation>('create_conversation'); if (alive) { conversation.value = result; input.value = ''; attachments.value = []; lastSeconds.value = null; await refreshList() } } catch (e) { report(e) } finally { loading.value = false }
}
async function send(retry?: Turn) {
  if (sending.value || loading.value || !props.ready || (!retry && !canSend.value)) return
  const pendingText = input.value.trim(), pendingImages = attachments.value
  if (!conversation.value) { await newConversation(); if (!conversation.value) return }
  const owner = conversation.value.id
  const content = retry?.content ?? pendingText
  const images = retry?.attachments ?? pendingImages
  const requestId = retry?.id ?? crypto.randomUUID()
  const draft = input.value
  sending.value = true
  emit('busy', true)
  error.value = ''
  closeConversationMenu()
  pendingDeleteId.value = null
  if (retry) retry.state = 'pending'
  else { input.value = ''; attachments.value = []; conversation.value.turns.push({ id: requestId, content, attachments: images, reply: null, state: 'pending', error: '', created_at: Date.now() }) }
  await scrollToBottom()
  const started = performance.now()
  try {
    await call('send_chat', { conversationId: owner, requestId, content, attachments: images })
    if (props.humanDelay) await new Promise(resolve => setTimeout(resolve, Math.min(2400, 600 + content.length * 8)))
    if (alive) { conversation.value = await call<Conversation>('get_conversation', { id: owner }); lastSeconds.value = (performance.now() - started) / 1000; await refreshList() }
  } catch (e) {
    if (alive) {
      report(e)
      try { conversation.value = await call<Conversation>('get_conversation', { id: owner }) } catch { /* Keep the visible pending text if the manager disconnected. */ }
      const turn = conversation.value?.turns.find(item => item.id === requestId)
      if (turn) { turn.state = 'failed'; turn.error = error.value }
      if (!retry && !turn) { input.value = draft || content; attachments.value = images }
    }
  } finally { sending.value = false; emit('busy', false); if (alive) await scrollToBottom() }
}
async function requestDelete(id: string) {
  closeConversationMenu()
  if (sending.value || loading.value || readingImages.value || !canDeleteConversation.value) return
  pendingDeleteId.value = id
  await nextTick(); deleteCancel.value?.focus()
}
async function removeConversation(id = conversation.value?.id) {
  if (!id || sending.value || loading.value || readingImages.value || !canDeleteConversation.value) return
  loading.value = true
  const wasCurrent = conversation.value?.id === id
  try {
    await call('delete_conversation', { id })
    drafts.delete(id)
    pendingDeleteId.value = null
    if (wasCurrent) { conversation.value = null; input.value = ''; attachments.value = [] }
    await refreshList()
    if (wasCurrent) { const next = conversations.value[0]; if (next) { loading.value = false; await openConversation(next.id) } }
  } catch (e) { report(e) } finally { loading.value = false }
}
function closeConversationMenu() { contextMenu.value = null }
async function showConversationMenu(event: MouseEvent | KeyboardEvent, id: string) {
  if (sending.value || loading.value || readingImages.value || !isDesktop) return
  event.preventDefault()
  menuTrigger = event.currentTarget as HTMLElement
  const bounds = menuTrigger.getBoundingClientRect()
  const pointer = 'clientX' in event && event.clientX > 0
  const x = pointer ? event.clientX : bounds.left
  const y = pointer ? event.clientY : bounds.bottom
  contextMenu.value = { id, x: Math.max(8, Math.min(x, window.innerWidth - 208)), y: Math.max(8, Math.min(y, window.innerHeight - 192)) }
  await nextTick()
  menuElement.value?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus()
}
function conversationKeydown(event: KeyboardEvent, id: string) {
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) void showConversationMenu(event, id)
}
function menuKeydown(event: KeyboardEvent) {
  if (event.key === 'Tab') { closeConversationMenu(); return }
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const items = Array.from(menuElement.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
  const index = items.indexOf(document.activeElement as HTMLButtonElement)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
  items[next]?.focus()
}
function dismissConversationActions(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (contextMenu.value) { closeConversationMenu(); menuTrigger?.focus() }
  if (!loading.value) { renameId.value = null; pendingDeleteId.value = null }
}
function trapDialogFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab') return
  const items = Array.from((event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)'))
  const target = event.shiftKey ? items.at(-1) : items[0]
  if ((event.shiftKey && document.activeElement === items[0]) || (!event.shiftKey && document.activeElement === items.at(-1))) { event.preventDefault(); target?.focus() }
}
async function requestRename(id: string) {
  closeConversationMenu()
  const item = conversations.value.find(item => item.id === id)
  if (!item || sending.value || loading.value || readingImages.value) return
  renameId.value = id; renameTitle.value = item.title || t('ui.new_conversation')
  await nextTick(); renameInput.value?.focus(); renameInput.value?.select()
}
async function renameConversation() {
  const id = renameId.value, title = renameTitle.value.trim()
  if (!id || !title || title.length > 80 || sending.value || loading.value) return
  loading.value = true
  try {
    const result = await call<Conversation>('rename_conversation', { id, title })
    if (!alive) return
    if (conversation.value?.id === id) conversation.value.title = result.title
    await refreshList(); renameId.value = null
  } catch (e) { report(e) } finally { loading.value = false }
}
async function moveConversation(direction: 'up' | 'down') {
  const id = contextMenu.value?.id
  closeConversationMenu()
  if (!id || sending.value || loading.value) return
  loading.value = true
  try { await call('move_conversation', { id, direction }); await refreshList() }
  catch (e) { report(e) } finally { loading.value = false }
}
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) { event.preventDefault(); void send() }
}
function date(value: number) { return new Intl.DateTimeFormat(locale.value, { month: 'short', day: 'numeric' }).format(value) }
function openDebug() { emit('debug', { conversationId: conversation.value?.id, query: input.value.trim() || conversation.value?.turns.at(-1)?.content || '' }) }
watch(() => props.ready, () => { if (props.ready) error.value = ''; else stickerPicker.value = false })
onMounted(async () => {
  document.addEventListener('pointerdown', closeConversationMenu)
  document.addEventListener('keydown', dismissConversationActions)
  window.addEventListener('resize', closeConversationMenu)
  window.addEventListener('scroll', closeConversationMenu, true)
  loading.value = true
  try { await refreshList(); loading.value = false; if (conversations.value[0]) await openConversation(conversations.value[0].id) } catch (e) { report(e) } finally { loading.value = false }
})
onUnmounted(() => {
  alive = false
  document.removeEventListener('pointerdown', closeConversationMenu)
  document.removeEventListener('keydown', dismissConversationActions)
  window.removeEventListener('resize', closeConversationMenu)
  window.removeEventListener('scroll', closeConversationMenu, true)
})
</script>

<template>
  <div class="chat-workspace">
    <aside class="conversation-sidebar" :aria-label="t('chat.conversations')">
      <div class="conversation-toolbar"><strong>{{ t('chat.conversations') }}</strong><button class="icon-button" :title="t('ui.new_conversation')" :aria-label="t('ui.new_conversation')" :disabled="sending || loading || !isDesktop" @click="newConversation"><Plus :size="18"/></button></div>
      <p v-if="!conversations.length" class="conversation-empty">{{ t('chat.no_conversations') }}</p>
      <div v-for="item in conversations" :key="item.id" class="conversation-entry" @contextmenu.prevent="showConversationMenu($event, item.id)" @keydown="conversationKeydown($event, item.id)">
        <button class="conversation-item" :class="{ selected: conversation?.id === item.id }" :disabled="sending || loading" :aria-current="conversation?.id === item.id ? 'true' : undefined" @click="openConversation(item.id)"><MessageCircle :size="15"/><span><strong>{{ item.title || t('ui.new_conversation') }}</strong><small>{{ date(item.updated_at) }}</small></span></button>
        <button class="icon-button conversation-menu-button" :title="t('chat.menu')" :aria-label="t('chat.menu') + ': ' + (item.title || t('ui.new_conversation'))" aria-haspopup="menu" :aria-expanded="contextMenu?.id === item.id" :disabled="sending || loading" @click.stop="showConversationMenu($event, item.id)"><Ellipsis :size="16"/></button>
      </div>
      <p class="conversation-storage">{{ t('chat.local_storage') }}</p>
    </aside>
    <section class="chat-thread">
      <div class="chat-heading"><div><h2>{{ friendName || t('ui.your_afterglow') }}</h2><p>{{ ready ? t('ui.ready_to_chat') : t('ui.prepare_the_core_and_chat_records_first') }}</p></div><div class="chat-heading-actions"><button v-if="debugEnabled" class="icon-button" :title="t('debug.open')" :aria-label="t('debug.open')" @click="openDebug"><Bug :size="17"/></button><button class="button secondary chat-import-button" :disabled="sending || loading" @click="emit('import')"><Upload :size="15"/>{{ t('ui.import_records') }}</button><button v-if="conversation" class="icon-button" :title="t(canDeleteConversation ? 'chat.delete' : 'chat.keep_last')" :aria-label="t('chat.delete')" :disabled="sending || loading || !canDeleteConversation" @click="requestDelete(conversation.id)"><Trash2 :size="17"/></button></div></div>
      <div ref="messagesElement" class="messages" role="log" :aria-label="t('ui.chat_message')" aria-live="polite" :aria-busy="sending || loading">
        <div v-if="!conversation?.turns.length" class="chat-empty"><img src="/afterglow-icon.svg" alt=""/><h1>{{ t('ui.some_words_are_worth_saying_again') }}</h1><p>{{ t('ui.continue_a_familiar_warmth_from_real_conversations') }}</p><button class="button secondary" @click="ready ? emit('import') : emit('setup')">{{ ready ? t('ui.import_chat_records') : t('ui.complete_setup') }}<ArrowRight :size="15"/></button><small>{{ isDesktop ? t('chat.saved_per_instance') : t('ui.browser_preview_does_not_collect_or_save') }}</small></div>
        <template v-for="(turn, index) in conversation?.turns" :key="turn.id">
          <div class="message user"><span class="message-author">{{ selfName || t('ui.me') }}</span><ChatContent v-if="turn.content" :content="turn.content" :instance-id="instanceId"/><div v-if="turn.attachments?.length" class="message-images"><img v-for="(attachment, imageIndex) in turn.attachments" :key="imageIndex" :src="attachment.preview" :alt="attachment.name"/></div><small v-if="turn.state === 'failed'" class="failed-state">{{ t('chat.failed') }}</small></div>
          <div v-if="turn.reply" class="message assistant"><span class="message-author">{{ friendName || 'Afterglow' }}</span><ChatContent :content="turn.reply" :instance-id="instanceId"/></div>
          <div v-if="turn.state === 'failed'" class="retry-message"><p>{{ turn.error || t('chat.interrupted') }}</p><button v-if="index === (conversation?.turns.length ?? 0) - 1" class="text-button" :disabled="sending || !ready" @click="send(turn)"><RefreshCw :size="13"/>{{ t('chat.retry') }}</button></div>
          <p v-if="turn.state === 'completed' && !turn.reply" class="silent-message">{{ t('ui.the_core_chose_not_to_reply_this') }}</p>
        </template>
        <div v-if="sending || loading" class="thinking"><LoaderCircle :size="15" class="spinning"/>{{ sending ? t('ui.preparing_a_reply') : t('chat.loading') }}</div>
      </div>
      <p v-if="error" class="chat-error" role="alert">{{ error }}</p>
      <div class="composer-wrap"><div class="composer-meta"><button @click="emit('settings')"><SlidersHorizontal :size="13"/>{{ presetLabel }}<ChevronRight :size="12"/></button><span>{{ lastSeconds === null ? t('ui.response_time_no_measurements_yet') : t('chat.last_seconds', { seconds: lastSeconds.toFixed(1) }) }}</span></div><div v-if="attachments.length" class="composer-images"><div v-for="(attachment, index) in attachments" :key="index"><img :src="attachment.preview" :alt="attachment.name"/><button class="icon-button" :aria-label="t('chat.remove_image', { name: attachment.name })" :disabled="sending" @click="attachments.splice(index, 1)"><X :size="13"/></button></div></div><div v-if="stickerPicker" class="chat-sticker-picker"><div class="section-heading"><strong>{{ t('stickers.picker') }}</strong><button class="icon-button" :aria-label="t('common.close')" @click="stickerPicker = false"><X :size="15"/></button></div><p v-if="stickerLoading" class="muted">{{ t('chat.loading') }}</p><p v-else-if="!availableStickers.length" class="muted">{{ t('stickers.picker_empty') }}</p><div class="sticker-picker-grid"><button v-for="sticker in availableStickers" :key="sticker.name + sticker.sha" type="button" :title="sticker.description" :disabled="sending || loading || !ready" @click="insertSticker(sticker)"><StickerImage :instance-id="instanceId" :name="sticker.name" :sha="sticker.sha"/><small>{{ sticker.name }}</small></button></div></div><form class="composer" @submit.prevent="send()"><button class="icon-button composer-tool attach-image" type="button" :title="t(visionEnabled ? 'chat.image_hint' : 'chat.image_enable')" :aria-label="t('chat.add_images')" :disabled="!isDesktop || !ready || sending || loading || readingImages || !visionEnabled" @click="pickImages"><LoaderCircle v-if="readingImages" :size="18" class="spinning"/><ImagePlus v-else :size="18"/></button><button class="icon-button composer-tool" type="button" :title="t('stickers.picker')" :aria-label="t('stickers.picker')" :aria-expanded="stickerPicker" :disabled="!isDesktop || !ready || sending || loading" @click="pickSticker"><SmilePlus :size="18"/></button><textarea ref="composerInput" v-model="input" maxlength="16000" :disabled="!ready || sending || loading" :placeholder="t('ui.write_what_you_want_to_say')" :aria-label="t('ui.chat_message')" rows="2" @keydown="onKeydown"/><button class="send-button" type="submit" :aria-label="t('ui.send_message')" :disabled="!canSend"><Send :size="19"/></button></form><p class="composer-disclaimer">{{ attachments.length ? t('chat.image_hint') : t('ui.afterglow_is_an_ai_companion_its_replies') }}</p></div>
    </section>
    <Teleport to="body">
      <div v-if="contextMenu" ref="menuElement" class="conversation-context-menu" role="menu" :aria-label="t('chat.menu')" :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }" @pointerdown.stop @contextmenu.prevent @keydown="menuKeydown">
        <button type="button" role="menuitem" @click="requestRename(contextMenu.id)"><Pencil :size="15"/>{{ t('chat.rename') }}</button>
        <button type="button" role="menuitem" :disabled="contextIndex <= 0" @click="moveConversation('up')"><ArrowUp :size="15"/>{{ t('chat.move_up') }}</button>
        <button type="button" role="menuitem" :disabled="contextIndex < 0 || contextIndex >= conversations.length - 1" @click="moveConversation('down')"><ArrowDown :size="15"/>{{ t('chat.move_down') }}</button>
        <button type="button" role="menuitem" class="danger-text" :disabled="!canDeleteConversation" :title="!canDeleteConversation ? t('chat.keep_last') : undefined" @click="requestDelete(contextMenu.id)"><Trash2 :size="15"/>{{ t('chat.delete') }}</button>
      </div>
      <div v-if="pendingDeleteId" class="modal-backdrop" @click.self="!loading && (pendingDeleteId = null)">
        <div class="instance-dialog conversation-delete-confirm" role="dialog" aria-modal="true" :aria-label="t('chat.delete')" @keydown="trapDialogFocus">
          <h2>{{ t('chat.delete') }}</h2><p>{{ t('chat.delete_notice') }}</p>
          <div class="dialog-actions"><button ref="deleteCancel" class="button secondary" :disabled="loading" @click="pendingDeleteId = null"><X :size="14"/>{{ t('common.cancel') }}</button><button class="button primary" :disabled="loading || !canDeleteConversation" @click="removeConversation(pendingDeleteId!)"><Check :size="14"/>{{ t('chat.confirm_delete') }}</button></div>
        </div>
      </div>
      <div v-if="renameId" class="modal-backdrop" @click.self="!loading && (renameId = null)">
        <form class="instance-dialog conversation-rename-dialog" role="dialog" aria-modal="true" :aria-label="t('chat.rename_title')" @submit.prevent="renameConversation" @keydown="trapDialogFocus">
          <h2>{{ t('chat.rename_title') }}</h2><label>{{ t('chat.title') }}<input ref="renameInput" v-model="renameTitle" maxlength="80" :disabled="loading"/></label>
          <div class="dialog-actions"><button class="button secondary" type="button" :disabled="loading" @click="renameId = null">{{ t('common.cancel') }}</button><button class="button primary" type="submit" :disabled="loading || !renameTitle.trim() || renameTitle.trim().length > 80">{{ t('chat.save_name') }}</button></div>
        </form>
      </div>
    </Teleport>
  </div>
</template>
