<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ImagePlus, LoaderCircle, Pencil, RefreshCw, Trash2, X } from 'lucide-vue-next'
import { t } from '../i18n'
import { chooseImages, isDesktop, rpc } from '../services/desktop'
import { invalidateStickers, type Sticker } from '../services/stickers'
import StickerImage from './StickerImage.vue'
const props = defineProps<{ instanceId: string; ready: boolean; disabled: boolean }>()
const emit = defineEmits<{ error: [message: string]; busy: [value: boolean] }>()
const items = ref<Sticker[]>([]), busy = ref(false), loaded = ref(false)
const owner = ref<Sticker['owner']>('shared'), filter = ref<'all' | Sticker['owner']>('all')
const name = ref(''), description = ref(''), tags = ref(''), path = ref(''), preview = ref(''), editing = ref(''), deleting = ref('')
const visible = computed(() => items.value.filter(item => filter.value === 'all' || item.owner === filter.value || item.owner === 'shared'))
const owners = ['self', 'ai', 'shared'] as const
let alive = true
function call<T>(method: string, args: Record<string, unknown> = {}) { return rpc<T>(method, { ...args, instanceId: props.instanceId }) }
async function run(action: () => Promise<void>) {
  if (busy.value || props.disabled) return
  busy.value = true; emit('busy', true)
  try { await action() } catch (error) { if (alive) emit('error', error instanceof Error ? error.message : String(error)) }
  finally { busy.value = false; emit('busy', false) }
}
async function refresh() { const result = await call<{ items: Sticker[] }>('stickers_list'); if (alive) { items.value = result.items; loaded.value = true } }
function reset() { editing.value = ''; name.value = ''; description.value = ''; tags.value = ''; path.value = ''; preview.value = ''; owner.value = 'shared' }
async function choose() { await run(async () => {
  const paths = await chooseImages(true)
  if (!paths.length) return
  const result = await call<{ images: { name: string; dataUrl: string }[] }>('read_chat_images', { paths })
  if (alive && result.images[0]) { path.value = paths[0]!; preview.value = result.images[0].dataUrl; if (!name.value) name.value = result.images[0].name.replace(/\.[^.]+$/, '').replace(/[^\w\u4e00-\u9fff-]/g, '_').slice(0, 32) }
}) }
function edit(item: Sticker) { editing.value = item.name; name.value = item.name; description.value = item.description; owner.value = item.owner; tags.value = item.tags.join(', '); path.value = ''; preview.value = '' }
async function save() { await run(async () => {
  await call(editing.value ? 'stickers_update' : 'stickers_create', { name: name.value, description: description.value, owner: owner.value, tags: tags.value.split(/[,，]/).map(value => value.trim()).filter(Boolean), ...(editing.value ? {} : { path: path.value }) })
  invalidateStickers(props.instanceId); reset(); await refresh()
}) }
async function remove() { await run(async () => { await call('stickers_delete', { name: deleting.value }); invalidateStickers(props.instanceId); if (editing.value === deleting.value) reset(); deleting.value = ''; await refresh() }) }
function loadWhenReady() { if (isDesktop && props.ready) void refresh().catch(error => { if (alive) emit('error', String(error)) }) }
watch(() => props.ready, value => { if (value) loadWhenReady() })
onMounted(loadWhenReady)
onUnmounted(() => { alive = false; emit('busy', false) })
</script>
<template>
  <section class="surface sticker-library">
    <div class="section-heading"><div><h2>{{ t('stickers.title') }}</h2><p class="muted">{{ t('stickers.notice') }}</p></div><button class="icon-button" :aria-label="t('analysis.refresh')" :disabled="busy || disabled || !ready" @click="run(refresh)"><RefreshCw :size="16"/></button></div>
    <form class="sticker-form" @submit.prevent="save">
      <div class="section-heading"><h3>{{ t(editing ? 'stickers.edit' : 'stickers.add') }}</h3><button v-if="editing" type="button" class="text-button" :disabled="busy" @click="reset"><X :size="14"/>{{ t('common.cancel') }}</button></div>
      <div v-if="!editing" class="sticker-file"><button type="button" class="button secondary" :disabled="busy || disabled || !ready || !isDesktop" @click="choose"><ImagePlus :size="15"/>{{ t('stickers.choose_image') }}</button><img v-if="preview" :src="preview" :alt="name"/><small class="muted">{{ t('stickers.file_hint') }}</small></div>
      <div class="form-grid"><label>{{ t('stickers.name') }}<input v-model="name" maxlength="32" required :disabled="!!editing || busy || disabled || !ready"/></label><label>{{ t('stickers.tags') }}<input v-model="tags" maxlength="820" :disabled="busy || disabled || !ready"/></label></div>
      <label>{{ t('stickers.description') }}<textarea v-model="description" maxlength="200" rows="2" required :disabled="busy || disabled || !ready" :placeholder="t('stickers.description_hint')"/></label>
      <div class="choice-buttons" role="group" :aria-label="t('stickers.owner')"><button v-for="option in owners" :key="option" type="button" class="button" :class="owner === option ? 'primary' : 'secondary'" :aria-pressed="owner === option" :disabled="busy || disabled || !ready" @click="owner = option">{{ t(option === 'self' ? 'stickers.self' : option === 'ai' ? 'stickers.ai' : 'stickers.shared') }}</button></div>
      <button class="button primary" type="submit" :disabled="busy || disabled || !ready || !name.trim() || !description.trim() || (!editing && !path)"><LoaderCircle v-if="busy" :size="14" class="spinning"/>{{ t(editing ? 'stickers.save' : 'stickers.upload') }}</button>
    </form>
    <div class="choice-buttons" role="group" :aria-label="t('stickers.filter')"><button v-for="option in (['all', 'self', 'ai'] as const)" :key="option" class="text-button" :class="{ selected: filter === option }" :aria-pressed="filter === option" @click="filter = option">{{ t(option === 'all' ? 'stickers.all' : option === 'self' ? 'stickers.self' : 'stickers.ai') }}</button></div>
    <p v-if="loaded && !visible.length" class="muted">{{ t('stickers.empty') }}</p>
    <div class="sticker-grid"><article v-for="item in visible" :key="item.name + item.sha" class="sticker-card"><StickerImage :instance-id="instanceId" :name="item.name" :sha="item.sha"/><strong>{{ item.name }}</strong><small>{{ t(item.owner === 'self' ? 'stickers.self' : item.owner === 'ai' ? 'stickers.ai' : 'stickers.shared') }}</small><p>{{ item.description }}</p><div class="component-actions"><button class="icon-button" :aria-label="t('stickers.edit') + ' ' + item.name" :disabled="busy || disabled || !ready" @click="edit(item)"><Pencil :size="15"/></button><button class="icon-button danger-text" :aria-label="t('stickers.delete') + ' ' + item.name" :disabled="busy || disabled || !ready" @click="deleting = item.name"><Trash2 :size="15"/></button></div><div v-if="deleting === item.name" class="sticker-delete"><p>{{ t('stickers.delete_confirm', { name: item.name }) }}</p><button class="text-button" :disabled="busy" @click="deleting = ''">{{ t('common.cancel') }}</button><button class="button secondary danger-text" :disabled="busy || disabled || !ready" @click="remove">{{ t('stickers.delete') }}</button></div></article></div>
  </section>
</template>
