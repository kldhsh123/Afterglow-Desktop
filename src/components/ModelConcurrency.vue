<script setup lang="ts">
import { computed } from 'vue'
import { ChevronDown, Minus, Plus } from 'lucide-vue-next'
import { t } from '../i18n'

const props = defineProps<{ id: string; modelValue?: number; defaultValue: number; hint: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: number] }>()
const count = computed(() => props.modelValue ?? props.defaultValue)
function update(value: number) {
  if (!props.disabled && Number.isInteger(value) && value >= 1 && value <= 64) emit('update:modelValue', value)
}
function commit(event: Event) {
  const input = event.target as HTMLInputElement
  const value = input.valueAsNumber
  if (Number.isInteger(value) && value >= 1 && value <= 64) update(value)
  else input.value = String(count.value)
}
</script>

<template>
  <details class="model-concurrency">
    <summary><span>{{ t('concurrency.advanced') }}</span><small>{{ t('concurrency.current', { count }) }}</small><ChevronDown :size="14"/></summary>
    <div class="concurrency-options">
      <div class="concurrency-row">
        <label :for="id">{{ t('concurrency.limit') }}</label>
        <div class="concurrency-control">
          <button type="button" :disabled="disabled || count <= 1" :aria-label="t('concurrency.decrease')" @click="update(count - 1)"><Minus :size="14"/></button>
          <input :id="id" :value="count" type="number" min="1" max="64" step="1" inputmode="numeric" :disabled="disabled" :aria-describedby="id + '-hint'" @change="commit"/>
          <button type="button" :disabled="disabled || count >= 64" :aria-label="t('concurrency.increase')" @click="update(count + 1)"><Plus :size="14"/></button>
        </div>
        <button type="button" class="text-button concurrency-reset" :disabled="disabled || count === defaultValue" @click="update(defaultValue)">{{ t('concurrency.reset', { count: defaultValue }) }}</button>
      </div>
      <p :id="id + '-hint'">{{ hint }}</p>
      <p>{{ t('concurrency.tradeoff') }}</p>
      <p>{{ t('concurrency.shared') }}</p>
      <small>{{ t('concurrency.apply') }}</small>
    </div>
  </details>
</template>

<style scoped>
.model-concurrency{margin:16px 0;border-block:1px solid var(--line)}
summary{display:flex;align-items:center;gap:10px;min-height:44px;cursor:pointer;list-style:none;font-size:12px;color:var(--ink)}
summary::-webkit-details-marker{display:none}
summary small{margin-left:auto;color:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
summary svg{color:var(--accent);transition:transform 180ms}
details[open] summary svg{transform:rotate(180deg)}
summary:focus-visible,.concurrency-control button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.concurrency-options{padding:4px 0 18px}
.concurrency-row{display:flex;align-items:center;flex-wrap:wrap;gap:14px;margin-bottom:12px}
.concurrency-row label{font-size:12px;color:var(--ink)}
.concurrency-control{display:flex;align-items:center;padding:3px;border:1px solid var(--line);border-radius:999px;background:var(--surface)}
.concurrency-control button{display:grid;place-items:center;width:30px;height:30px;border-radius:50%;background:transparent;color:var(--ink);transition:background 180ms,transform 180ms}
.concurrency-control button:hover:enabled{background:#ebe3cd}
.concurrency-control button:active:enabled{transform:scale(.94)}
.concurrency-control button:disabled{opacity:.35;cursor:not-allowed}
.concurrency-control input{width:52px;padding:4px;border:0;background:transparent;text-align:center;font-size:13px;color:var(--ink);font-variant-numeric:tabular-nums;appearance:textfield;-moz-appearance:textfield}
.concurrency-control input::-webkit-inner-spin-button,.concurrency-control input::-webkit-outer-spin-button{appearance:none;margin:0}
.concurrency-control input:focus-visible{outline:2px solid var(--accent);outline-offset:0;border-radius:4px}
.concurrency-options p{margin:6px 0;font-size:11px;line-height:1.8;color:var(--muted)}
.concurrency-options>small{display:block;margin-top:10px;font-size:10px;color:var(--accent)}
.concurrency-reset{font-size:11px}
@media(prefers-reduced-motion:reduce){summary svg,.concurrency-control button{transition:none}}
</style>
