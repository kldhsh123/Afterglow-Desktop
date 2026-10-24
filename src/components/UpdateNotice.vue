<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ArrowUpRight, X } from 'lucide-vue-next'
import { isDesktop, rpc } from '../services/desktop'
import { t } from '../i18n'

defineProps<{ visible: boolean }>()
const emit = defineEmits<{ open: [] }>()
interface Entry { version?: string; currentVersion?: string; available?: boolean; failed?: boolean }
interface Status { checking: boolean; core?: Entry; desktop?: Entry }
const status = ref<Status | null>(null)
const dismissed = ref(false)
const available = computed(() => [
  status.value?.core?.available ? 'Afterglow ' + status.value.core.version : '',
  status.value?.desktop?.available ? t('updates.desktop_short') + ' ' + status.value.desktop.version : '',
].filter(Boolean).join(' · '))
let timer: ReturnType<typeof setTimeout> | undefined
let closed = false
async function check(initial = false) {
  try {
    const result = await rpc<Status>(initial ? 'start_update_checks' : 'repository_update_status')
    if (closed) return
    status.value = result
    if (result.checking) timer = setTimeout(() => void check(), 2000)
  } catch { /* Checking for updates must never interrupt language choice or chat. */ }
}
onMounted(() => { if (isDesktop) void check(true) })
onUnmounted(() => { closed = true; clearTimeout(timer) })
</script>

<template>
  <aside v-if="visible && available && !dismissed" class="repository-update-notice" role="status">
    <div><strong>{{ t('updates.new_versions') }}</strong><p>{{ available }}</p></div>
    <button class="text-button" @click="emit('open')">{{ t('updates.view') }}<ArrowUpRight :size="14"/></button>
    <button class="icon-button" :aria-label="t('common.close')" @click="dismissed = true"><X :size="14"/></button>
  </aside>
</template>

<style scoped>
.repository-update-notice { position: fixed; top: calc(var(--titlebar-height, 0px) + 14px); right: 22px; z-index: 55; display: flex; align-items: center; gap: 18px; max-width: min(540px, calc(100vw - 32px)); padding: 13px 14px 13px 18px; background: var(--surface); border: 1px solid #cdbb9d; border-radius: 8px; box-shadow: 0 8px 28px #8b5a2b12; }
.repository-update-notice strong { font-size: 12px; font-weight: 500; }
.repository-update-notice p { margin-top: 3px; color: #8b795f; font-size: 10px; overflow-wrap: anywhere; }
</style>
