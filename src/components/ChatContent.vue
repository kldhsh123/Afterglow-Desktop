<script setup lang="ts">
import { computed } from 'vue'
import StickerImage from './StickerImage.vue'
const props = defineProps<{ content: string; instanceId: string }>()
const parts = computed(() => {
  const result: { text: string; sticker?: string }[] = []
  const pattern = /\[sticker(?::|=)([^\]\s]+)\]/gi
  let position = 0
  for (const match of props.content.matchAll(pattern)) {
    const offset = match.index ?? 0
    if (offset > position) result.push({ text: props.content.slice(position, offset) })
    result.push({ text: match[0], ...(match[1]!.length <= 32 ? { sticker: match[1]! } : {}) })
    position = offset + match[0].length
  }
  if (position < props.content.length) result.push({ text: props.content.slice(position) })
  return result
})
</script>
<template><div class="chat-message-content"><template v-for="(part, index) in parts" :key="index"><StickerImage v-if="part.sticker" :instance-id="instanceId" :name="part.sticker"/><span v-else>{{ part.text }}</span></template></div></template>
