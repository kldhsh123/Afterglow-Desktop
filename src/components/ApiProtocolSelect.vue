<script setup lang="ts">
import { t } from '../i18n'
defineProps<{ modelValue?: 'chat_completions' | 'responses'; label: string }>()
defineEmits<{ 'update:modelValue': [value: 'chat_completions' | 'responses'] }>()
</script>

<template>
  <fieldset class="protocol-field">
    <legend>{{ t('services.api_protocol') }}</legend>
    <div class="protocol-switch" role="radiogroup" :aria-label="label + ' · ' + t('services.api_protocol')">
      <button v-for="value in ['chat_completions', 'responses'] as const" :key="value" type="button" role="radio" :aria-checked="(modelValue || 'chat_completions') === value" @click="$emit('update:modelValue', value)">
        <span>{{ value === 'responses' ? 'Responses' : 'Chat Completions' }}</span>
        <small>{{ value === 'responses' ? '/responses' : '/chat/completions' }}</small>
      </button>
    </div>
    <small class="protocol-help">{{ t('services.protocol_hint') }}</small>
  </fieldset>
</template>
