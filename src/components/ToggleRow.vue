<script setup lang="ts">
import { useId } from 'vue'
defineProps<{ modelValue: boolean; label: string; description: string; cost?: string; disabled?: boolean }>()
defineEmits<{ 'update:modelValue': [value: boolean] }>()
const labelId = useId()
</script>
<template><div class="toggle-row"><div><strong :id="labelId">{{ label }}</strong><p>{{ description }}</p><small v-if="cost">{{ cost }}</small></div><button class="switch" type="button" role="switch" :aria-checked="modelValue" :aria-labelledby="labelId" :disabled="disabled" @click="$emit('update:modelValue', !modelValue)"><span/></button></div></template>
