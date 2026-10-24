<script setup lang="ts">
import { computed } from 'vue'
import { locale, t } from '../i18n'
import type { AnalysisReport } from '../domain/analysis'
const props = defineProps<{ report: AnalysisReport; name: string }>()
const meaningful = computed(() => !!(props.report.summary?.trim() || props.report.events?.length || props.report.phases?.length || props.report.sections?.some(s => s.observations.length) || props.report.habits?.length || props.report.source_session_count))
function percent(value: number) { return new Intl.NumberFormat(locale.value, { style: 'percent', maximumFractionDigits: 0 }).format(value) }
</script>
<template>
  <div class="analysis-report">
    <div class="section-heading"><h3>{{ name }}</h3><small v-if="report.generated_at" class="muted">{{ report.generated_at }}</small></div>
    <p v-if="!meaningful" class="inline-notice" role="status">{{ t('analysis.no_findings') }}</p>
    <p v-if="report.disclaimer" class="muted">{{ report.disclaimer }}</p>
    <p v-if="report.summary" class="report-summary">{{ report.summary }}</p>
    <article v-for="phase in report.phases" :key="phase.start_date + phase.title" class="report-entry"><small>{{ phase.start_date }} — {{ phase.end_date }}</small><h4>{{ phase.title }}</h4><p>{{ phase.summary }}</p></article>
    <article v-for="event in report.events" :key="event.event_id" class="report-entry"><small>{{ event.date }}</small><h4>{{ event.title }}</h4><p>{{ event.summary }}</p><details v-if="event.evidence?.length"><summary>{{ t('analysis.evidence') }}</summary><blockquote v-for="(evidence, index) in event.evidence" :key="index">{{ evidence.quote }}<small>{{ evidence.date }}</small></blockquote></details></article>
    <section v-for="section in report.sections" :key="section.key"><h4>{{ section.title }}</h4><p v-if="!section.observations.length" class="muted">{{ t('analysis.no_section_findings') }}</p><article v-for="(observation, index) in section.observations" :key="index" class="report-entry"><strong>{{ observation.dimension }}</strong><p>{{ observation.claim }}</p><small v-if="observation.confidence !== undefined" class="muted">{{ t('analysis.confidence', { value: percent(observation.confidence) }) }}</small><details v-if="observation.evidence?.length || observation.counterexamples?.length || observation.alternative_explanations?.length"><summary>{{ t('analysis.evidence_and_limits') }}</summary><blockquote v-for="(evidence, i) in observation.evidence" :key="i">{{ evidence.quote }}<small>{{ evidence.date }}</small></blockquote><p v-for="(text, i) in observation.counterexamples" :key="'counter-' + i">{{ t('analysis.counterexample') }}: {{ text }}</p><p v-for="(text, i) in observation.alternative_explanations" :key="'alternative-' + i">{{ t('analysis.alternative') }}: {{ text }}</p></details></article></section>
    <dl v-if="report.source_session_count !== undefined" class="report-stats"><div><dt>{{ t('analysis.sessions') }}</dt><dd>{{ report.source_session_count }}</dd></div><div><dt>{{ t('analysis.initiative') }}</dt><dd>{{ report.friend_initiative_count ?? report.initiative_count ?? 0 }}</dd></div><div><dt>{{ t('analysis.initiative_rate') }}</dt><dd>{{ percent(report.initiative_rate ?? 0) }}</dd></div></dl>
    <details><summary>{{ t('analysis.raw_json') }}</summary><pre>{{ JSON.stringify(report, null, 2) }}</pre></details>
  </div>
</template>
