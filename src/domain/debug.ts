export interface CallStats {
  count: number; error_count: number; error_rate: number
  avg_latency_ms: number; p50_latency_ms: number; p95_latency_ms: number
  last?: { ts_ms: number; latency_ms: number; status: string; detail: string }[]
}
export interface ModelCall {
  ts_ms: number; trace_id: string; stage: string; attempt: number; model: string
  url: string; stream: boolean; latency_ms: number; status: string
  status_code: number | null; upstream_request_id: string; error: string
  request: unknown; response: unknown
}
export interface DebugSnapshot {
  stats: {
    version: string; memory: Record<string, number>; calls: Record<string, CallStats>
    model_chain: ModelCall[]; database: Record<string, unknown>
    life: { snapshot?: Record<string, unknown>; daily_plan?: unknown[]; recent_timeline?: unknown[]; [key: string]: unknown }
    proactive: Record<string, unknown>; writeback: Record<string, unknown>
  }
  config: Record<string, unknown>
}
export interface MemoryHit {
  chunk_id: string; kind: string; text: string; score: number; rank: number
  sender_name?: string; source?: string; timestamp_ms?: number
}
export interface SearchResult {
  fused?: MemoryHit[]; response_pairs?: MemoryHit[]; friend_examples?: MemoryHit[]
  dialogue_windows?: MemoryHit[]; history_images?: MemoryHit[]; recent_live?: MemoryHit[]
  trace_id?: string
}
export interface ProactivePreview {
  message?: { content?: string; [key: string]: unknown } | string
  silenced?: boolean; trace_id?: string; [key: string]: unknown
}
