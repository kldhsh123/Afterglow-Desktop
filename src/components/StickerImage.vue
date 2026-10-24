<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { stickerImage } from '../services/stickers'
import { t } from '../i18n'
const props = defineProps<{ instanceId: string; name: string; sha?: string }>()
const source = ref(''), failure = ref(''), element = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | undefined, alive = true, generation = 0, visible = false
async function load() {
  const request = ++generation
  source.value = ''; failure.value = ''
  try { const value = await stickerImage(props.instanceId, props.name, props.sha); if (alive && request === generation) source.value = value }
  catch (error) { if (alive && request === generation) failure.value = String(error) }
}
watch(() => [props.instanceId, props.name, props.sha], () => { if (visible) void load() })
onMounted(() => {
  if (!element.value || !('IntersectionObserver' in window)) { visible = true; void load(); return }
  observer = new IntersectionObserver(entries => { if (entries.some(entry => entry.isIntersecting)) { visible = true; observer?.disconnect(); void load() } }, { rootMargin: '120px' })
  observer.observe(element.value)
})
onUnmounted(() => { alive = false; observer?.disconnect() })
</script>
<template><span ref="element" class="sticker-image" :title="failure || name"><img v-if="source" :src="source" :alt="name" loading="lazy" @error="source = ''; failure = t('stickers.image_failed')"/><span v-else>{{ failure ? '[sticker:' + name + ']' : name }}</span></span></template>
