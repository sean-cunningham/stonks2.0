import { apiRequest } from "./client";
import type { DashboardResponse, RuntimeView } from "../types/dashboard";

function routeBase(symbol: string, strategyId: string): string {
  return `/paper/strategy/${symbol}/${strategyId}`;
}

export function fetchDashboard(symbol: string, strategyId: string): Promise<DashboardResponse> {
  return apiRequest<DashboardResponse>(`${routeBase(symbol, strategyId)}/dashboard`);
}

export function setPause(symbol: string, strategyId: string, paused: boolean): Promise<RuntimeView> {
  return apiRequest<RuntimeView>(`${routeBase(symbol, strategyId)}/runtime/${paused ? "pause" : "resume"}`, {
    method: "POST",
  });
}

export function setEntryEnabled(symbol: string, strategyId: string, enabled: boolean): Promise<RuntimeView> {
  return apiRequest<RuntimeView>(
    `${routeBase(symbol, strategyId)}/runtime/${enabled ? "entry-enable" : "entry-disable"}`,
    {
      method: "POST",
    }
  );
}

export function setExitEnabled(symbol: string, strategyId: string, enabled: boolean): Promise<RuntimeView> {
  return apiRequest<RuntimeView>(`${routeBase(symbol, strategyId)}/runtime/${enabled ? "exit-enable" : "exit-disable"}`, {
    method: "POST",
  });
}

export function closeNow(symbol: string, strategyId: string, paperTradeId: number): Promise<unknown> {
  return apiRequest(`${routeBase(symbol, strategyId)}/positions/${paperTradeId}/close-now`, { method: "POST" });
}
