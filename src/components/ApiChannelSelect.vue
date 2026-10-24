<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Check, ChevronDown, Globe2, Waypoints } from 'lucide-vue-next'
import { t } from '../i18n'

const props = defineProps<{ id: string; modelValue: string; channels: { value: string; label: string }[]; label: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const active = ref(0)
const options = computed(() => props.channels.map(channel => ({ ...channel,
  description: t(channel.value === 'custom' ? 'channels.custom_hint' : 'channels.official_hint'),
  icon: channel.value === 'custom' ? Waypoints : Globe2,
})))
const selected = computed(() => options.value.find(option => option.value === props.modelValue))
function reveal(index?: number) {
  open.value = true
  active.value = index ?? Math.max(0, options.value.findIndex(option => option.value === props.modelValue))
}
async function choose(index: number) {
  emit('update:modelValue', options.value[index].value)
  open.value = false
  await nextTick()
  trigger.value?.focus()
}
function keydown(event: KeyboardEvent) {
  if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault()
    if (!open.value) reveal(event.key === 'Home' ? 0 : event.key === 'End' ? options.value.length - 1 : undefined)
    else active.value = event.key === 'Home' ? 0 : event.key === 'End' ? options.value.length - 1 : (active.value + (event.key === 'ArrowUp' ? -1 : 1) + options.value.length) % options.value.length
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) void choose(active.value)
    else reveal()
  } else if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    event.stopPropagation()
    open.value = false
  } else if (event.key === 'Tab') open.value = false
}
function outside(event: PointerEvent) { if (!root.value?.contains(event.target as Node)) open.value = false }
function blur(event: FocusEvent) { if (!root.value?.contains(event.relatedTarget as Node | null)) open.value = false }
function hideMenu(element: Element) { element.setAttribute('aria-hidden', 'true'); element.setAttribute('inert', '') }
onMounted(() => document.addEventListener('pointerdown', outside))
onUnmounted(() => document.removeEventListener('pointerdown', outside))
</script>

<template>
  <div ref="root" class="channel-select" @focusout="blur">
    <button :id="id" ref="trigger" class="channel-trigger" type="button" role="combobox" aria-haspopup="listbox" :aria-label="label" :aria-expanded="open" :aria-controls="id + '-options'" :aria-activedescendant="open ? id + '-option-' + active : undefined" @click="open ? open = false : reveal()" @keydown="keydown">
      <span class="channel-icon"><component :is="selected?.icon || Waypoints" :size="17" :stroke-width="1.6" /></span>
      <span class="channel-trigger-copy"><strong>{{ selected?.label || modelValue }}</strong><small>{{ selected?.description || t('channels.custom_hint') }}</small></span>
      <ChevronDown :size="16" class="channel-chevron" :class="{ expanded: open }" />
    </button>
    <Transition name="channel-menu" @before-leave="hideMenu">
      <ul v-if="open" :id="id + '-options'" class="channel-options" role="listbox" :aria-hidden="!open" :inert="!open" :aria-label="label">
        <li v-for="(option, index) in options" :id="id + '-option-' + index" :key="option.value" role="option" :aria-selected="modelValue === option.value" :class="{ highlighted: active === index, selected: modelValue === option.value }" @pointermove="active = index" @mousedown.prevent @click="choose(index)">
          <span class="channel-icon"><component :is="option.icon" :size="17" :stroke-width="1.6" /></span>
          <span class="channel-option-copy"><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span>
          <Check v-if="modelValue === option.value" :size="16" />
        </li>
      </ul>
    </Transition>
  </div>
</template>
