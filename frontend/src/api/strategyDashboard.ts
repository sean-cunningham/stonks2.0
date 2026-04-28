import { apiRequest } from "./client";
import type { DashboardResponse, RuntimeView } from "../types/dashboard";

/** POST /runtime/* returns this shape; includes `strategy_id` from the coordinator. */
export type StrategyOneRuntimeMutationResponse = RuntimeView & { strategy_id?: string };
export type StrategyCatalogItem = {
  id: string;
  name: string;
  paper_only: boolean;
  live_order_routing: boolean;
  ai_enabled: boolean;
  options_scope: string;
  universe: string[];
  status: string;
};

export type StrategyCatalogResponse = {
  strategies: StrategyCatalogItem[];
};

export type PauseAllRuntimeResponse = {
  action: "pause_all" | "resume_all";
  strategies: Array<{
    strategy_id: string;
    paused: boolean;
    entry_enabled: boolean;
    exit_enabled: boolean;
    scheduler_enabled: boolean;
  }>;
};

function routeBase(symbol: string, strategyId: string): string {
  return `/paper/strategy/${symbol}/${strategyId}`;
}

export function fetchDashboard(symbol: string, strategyId: string): Promise<DashboardResponse> {
  return apiRequest<DashboardResponse>(`${routeBase(symbol, strategyId)}/dashboard`);
}

export function fetchStrategyCatalog(): Promise<StrategyCatalogResponse> {
  return apiRequest<StrategyCatalogResponse>("/system/strategies");
}

export function setPause(symbol: string, strategyId: string, paused: boolean): Promise<StrategyOneRuntimeMutationResponse> {
  return apiRequest<StrategyOneRuntimeMutationResponse>(
    `${routeBase(symbol, strategyId)}/runtime/${paused ? "pause" : "resume"}`,
    {
      method: "POST",
    }
  );
}

export function setEntryEnabled(
  symbol: string,
  strategyId: string,
  enabled: boolean
): Promise<StrategyOneRuntimeMutationResponse> {
  return apiRequest<StrategyOneRuntimeMutationResponse>(
    `${routeBase(symbol, strategyId)}/runtime/${enabled ? "entry-enable" : "entry-disable"}`,
    {
      method: "POST",
    }
  );
}

export function setExitEnabled(
  symbol: string,
  strategyId: string,
  enabled: boolean
): Promise<StrategyOneRuntimeMutationResponse> {
  return apiRequest<StrategyOneRuntimeMutationResponse>(
    `${routeBase(symbol, strategyId)}/runtime/${enabled ? "exit-enable" : "exit-disable"}`,
    {
      method: "POST",
    }
  );
}

export function closeNow(symbol: string, strategyId: string, paperTradeId: number): Promise<unknown> {
  return apiRequest(`${routeBase(symbol, strategyId)}/positions/${paperTradeId}/close-now`, { method: "POST" });
}

/** Strategy 1 paper: force-close at $0 when the held contract cannot be quoted. */
export function emergencyCloseUnquoted(symbol: string, strategyId: string, paperTradeId: number): Promise<unknown> {
  return apiRequest(
    `${routeBase(symbol, strategyId)}/positions/${paperTradeId}/emergency-close-unquoted`,
    { method: "POST" }
  );
}

export function setPauseAll(paused: boolean): Promise<PauseAllRuntimeResponse> {
  return apiRequest<PauseAllRuntimeResponse>(`/paper/runtime/${paused ? "pause-all" : "resume-all"}`, {
    method: "POST",
  });
}

export function resetDashboardStats(symbol: string, strategyId: string): Promise<unknown> {
  return apiRequest(`${routeBase(symbol, strategyId)}/dashboard/reset`, { method: "POST" });
}
