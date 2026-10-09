/** Mirrors the API contract in src/quilora/api/app.py. */

export interface ToolCallView {
  name: string;
  ok: boolean;
  error_code: string | null;
  duration_ms: number;
}

export interface TurnMeta {
  stop_reason: string;
  iterations: number;
  latency_ms: number;
  cost_usd: number | null;
  usage: Record<string, number>;
  tools: ToolCallView[];
  flags: string[];
  model: string;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  handed_off: boolean;
  ticket_id: string | null;
  meta: TurnMeta;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'error';
  text: string;
  meta?: TurnMeta;
}
