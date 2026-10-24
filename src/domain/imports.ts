export interface Candidate { uid: string; name: string; role_hint: string }
export interface ImportedFile {
  name: string; saved_as: string; size: number; format: string; format_label: string
  total_messages: number; candidates: Candidate[]; error: string; ai_converted?: boolean
  conversion_stats?: { source_records: number; converted_messages: number; skipped_records: number; source_warning?: string }
  identity_previews?: Record<string, string>
  rule_reused?: boolean
}
export interface PreviewFile { name: string; size: number }
export interface ImportTask { task_id: string; status: string; stage?: string; progress?: number; error?: string; report?: unknown }

export function validImportIdentities(files: ImportedFile[], selfUids: string[], friendUids: string[]): boolean {
  if (!files.length || !selfUids.length || !friendUids.length || selfUids.some(uid => friendUids.includes(uid))) return false
  const all = new Set(files.flatMap(file => file.candidates.map(candidate => candidate.uid)))
  if ([...selfUids, ...friendUids].some(uid => !all.has(uid))) return false
  return files.every(file => !file.error && file.format !== 'unknown' &&
    file.candidates.some(candidate => selfUids.includes(candidate.uid)) &&
    file.candidates.some(candidate => friendUids.includes(candidate.uid)))
}

export function summarizeImport(report: unknown) {
  if (!report || typeof report !== 'object' || !('files' in report) || !Array.isArray(report.files)) return null
  const files = report.files.filter((entry): entry is { file: string; report: Record<string, unknown> } =>
    !!entry && typeof entry === 'object' && typeof entry.file === 'string' &&
    !!entry.report && typeof entry.report === 'object')
  if (!files.length) return null
  const sum = (key: string) => files.reduce((total, entry) => total +
    (typeof entry.report[key] === 'number' && Number.isFinite(entry.report[key]) ? entry.report[key] as number : 0), 0)
  const indices = 'vector_indices' in report ? report.vector_indices : null
  return {
    files: files.map(entry => entry.file),
    messages: sum('parsed_messages'),
    skipped: sum('skipped_messages'),
    failed: 'failed_chunks' in report && typeof report.failed_chunks === 'number' ? report.failed_chunks :
      sum('failed_friend') + sum('failed_response_pairs') + sum('failed_window'),
    seconds: sum('duration_seconds'),
    written: sum('upserted_friend') + sum('upserted_response_pairs') + sum('upserted_window'),
    smallIndex: !!indices && typeof indices === 'object' && Object.values(indices).some(value => typeof value === 'string' && value.startsWith('skip_small')),
  }
}
