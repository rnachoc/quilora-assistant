// Author: Ignacio Rodríguez Caro
/** Mirrors the API contract in src/quilora/api/app.py. */

/** A tool the agent used during a turn, without its arguments. */
export interface ToolCallView {
  name: string;
  ok: boolean;
  error_code: string | null;
  duration_ms: number;
}

/** Diagnostics for one turn: stop reason, model calls, latency, tokens, cost, flags. */
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

/** Response of POST /api/chat. */
export interface ChatResponse {
  session_id: string;
  reply: string;
  handed_off: boolean;
  ticket_id: string | null;
  meta: TurnMeta;
}

/** A message as rendered in the widget ('error' is a local connection problem). */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'error';
  text: string;
  meta?: TurnMeta;
}
