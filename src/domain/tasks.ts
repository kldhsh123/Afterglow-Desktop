import { t } from '../i18n'
const labels = {
  pending: 'task.pending', running: 'task.running', processing: 'task.running',
  done: 'task.done', completed: 'task.done', failed: 'task.failed', cancelled: 'task.cancelled', cancelling: 'task.cancelling',
} as const
export function taskLabel(status: string): string { return t(labels[status as keyof typeof labels] ?? 'task.running') }
