// Typed client for the smart-llm admin API. Mirrors the endpoints the Flutter
// UI uses (see flutter_package/lib/src/services/ai_agents_service.dart):
//   /api/v1/ai-agents/          /api/v1/ai-skills/
//   /api/v1/ai-agents/llm-keys/ /api/v1/ai-usage/cost-dashboard

const BASE = (import.meta.env.VITE_API_BASE ?? "") + "/api/v1";

export interface Skill {
  id: string;
  name: string;
  label?: string | null;
  description?: string | null;
}

export interface Agent {
  id: string;
  company_id: string;
  name: string;
  label?: string | null;
  description?: string | null;
  provider_type: string;
  model_name?: string | null;
  response_format: string;
  is_active: boolean;
  is_custom: boolean;
  skills: Skill[];
}

export interface LlmKey {
  id: string;
  company_id: string;
  provider: string;
  is_active: boolean;
}

export interface Paged<T> {
  data: T[];
  count: number;
}

// The cost dashboard shape is provider-dependent; keep it permissive and render
// whatever numeric/labelled fields come back.
export interface CostDashboard {
  total_cost_usd?: number;
  budget_usd?: number | null;
  window?: string;
  by_company?: Record<string, number>;
  by_model?: Record<string, number>;
  [k: string]: unknown;
}

function authHeaders(): Record<string, string> {
  const token =
    typeof localStorage !== "undefined"
      ? localStorage.getItem("smart_llm_token")
      : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders() },
  });
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText} for ${path}`);
  }
  return (await resp.json()) as T;
}

export const api = {
  agents: () => get<Paged<Agent>>("/ai-agents/"),
  skills: () => get<Paged<Skill>>("/ai-skills/"),
  keys: () => get<Paged<LlmKey>>("/ai-agents/llm-keys/"),
  costDashboard: () => get<CostDashboard>("/ai-usage/cost-dashboard"),
};
