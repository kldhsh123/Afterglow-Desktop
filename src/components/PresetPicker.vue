<script setup lang="ts">
import { t, locale, setLocale, supportedLocales } from "../i18n"
import { Check, Zap, Scale, Sparkles } from 'lucide-vue-next'
import { presets, type PresetId } from '../domain/settings'
defineProps<{ modelValue: PresetId }>()
defineEmits<{ 'update:modelValue': [id: PresetId] }>()
const icons = { quick: Zap, balanced: Scale, careful: Sparkles }
</script>
<template>
  <div class="preset-grid" role="radiogroup" :aria-label="t('ui.reply_preset')">
    <button v-for="preset in presets" :key="preset.id" class="preset-card" :class="{ selected: modelValue === preset.id }" role="radio" :aria-checked="modelValue === preset.id" @click="$emit('update:modelValue', preset.id)">
      <span class="preset-top"><component :is="icons[preset.id]" :size="21" :stroke-width="1.6"/><span v-if="preset.id === 'quick'" class="recommend">{{ t('ui.recommended') }}</span><span v-else class="radio-mark"><Check v-if="modelValue === preset.id" :size="12"/></span></span>
      <strong>{{ preset.name }}</strong><span class="preset-tagline">{{ preset.tagline }}</span><span class="preset-description">{{ preset.description }}</span>
      <span class="preset-foot">{{ preset.tradeoff }}</span>
    </button>
  </div>
</template>
