export interface Evidence { quote: string; date?: string; session_id?: string }
export interface Observation { dimension: string; claim: string; subject?: string; confidence?: number; evidence?: Evidence[]; counterexamples?: string[]; alternative_explanations?: string[] }
export interface AnalysisReport {
  generated_at?: string; disclaimer?: string; summary?: string; source_message_count?: number;
  events?: { event_id: string; date: string; title: string; summary: string; evidence?: Evidence[] }[];
  phases?: { title: string; start_date: string; end_date: string; summary: string }[];
  sections?: { key: string; title: string; observations: Observation[] }[];
  habits?: Observation[]; initiative_count?: number; friend_initiative_count?: number; initiative_rate?: number;
  source_session_count?: number; range_start?: string; range_end?: string;
}
export interface AnalysisDiagnostics {
  prompt_ready: { personalityPrompt: boolean; lifeContext: boolean };
  state: 'empty' | 'partial' | 'available' | 'pending'; has_reports: boolean; events: number; observations: number;
  task_id?: string; model_responses?: { reason: string; protocol?: string; finish_reason?: string; requested_tokens?: number; completion_tokens?: number; reasoning_tokens?: number; content_chars?: number; reasoning_present?: boolean; http_status?: number }[];
  available_reports: string[]; blocks: number; completed: number; skipped: number; empty_reports: string[]; directory: string;
  failures: { block_id: string; message: string; stage?: string; attempts?: { error: string; output_empty: boolean }[] }[];
}
