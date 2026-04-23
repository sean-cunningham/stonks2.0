/**
 * Presentation-only mapping from backend / evaluator machine strings to plain English.
 * Raw values stay available in technical/debug sections.
 */

export function snakeToTitleCase(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const DECISIONS: Record<string, string> = {
  no_trade: "No trade right now",
  candidate_call: "Call setup detected",
  candidate_put: "Put setup detected",
};

export function humanizeDecision(decision: string): string {
  return DECISIONS[decision] ?? snakeToTitleCase(decision);
}

const CYCLE_RESULTS: Record<string, string> = {
  no_action: "No action taken",
  opened: "Opened a trade",
  closed: "Closed a trade",
  error: "Error",
  skipped_paused: "Skipped because the bot is paused",
};

export function humanizeCycleResult(result: string | null | undefined): string {
  if (result == null || result === "") return "—";
  return CYCLE_RESULTS[result] ?? snakeToTitleCase(result);
}

/** Badge category after derived logic (opened, closed, error, blocked, no_action, …) */
export function humanizeCycleBadgeCategory(category: string): string {
  if (category === "blocked") return "Auto-open blocked";
  return humanizeCycleResult(category);
}

const BLOCKER_DETAILS: Record<string, string> = {
  market_closed: "The market is closed",
  stale_quote: "Live market data is stale",
  stale_chain: "Option chain data is stale",
  stale_1m_bars: "Intraday bars are stale",
  startup_not_initialized: "Market data has not finished starting up",
  none: "No issue",
};

const BLOCKER_PREFIXES: Record<string, string> = {
  context_not_live_ready: "Context is not ready for live trading",
  market_not_ready: "Live market data is not ready",
  chain_not_acceptable: "Option chain is not usable",
  missing_metrics: "Required market context is missing",
  no_trade_zone: "Price is in a no-trade (chop) zone",
  mixed: "Mixed signals between VWAP and the opening range",
  conflicting_bull_and_bear_structural_paths: "Conflicting bullish and bearish structure",
  no_acceptable_option_contract_in_intraday_dte_band_2_5: "No suitable option in the 2–5 day window",
  atr_non_positive: "ATR is not valid",
  missing_underlying_reference: "Missing underlying reference price",
};

export function humanizeBlocker(blocker: string): string {
  const idx = blocker.indexOf(":");
  if (idx === -1) {
    return BLOCKER_PREFIXES[blocker] ?? BLOCKER_DETAILS[blocker] ?? snakeToTitleCase(blocker);
  }
  const prefix = blocker.slice(0, idx);
  const detail = blocker.slice(idx + 1);
  const detailHuman = BLOCKER_DETAILS[detail] ?? snakeToTitleCase(detail.replace(/:/g, " "));
  const prefixHuman = BLOCKER_PREFIXES[prefix];
  if (prefixHuman && detailHuman) return `${prefixHuman}: ${detailHuman}`;
  if (prefixHuman) return `${prefixHuman} (${detailHuman}).`;
  return `${snakeToTitleCase(prefix)}: ${detailHuman}`;
}

const PAPER_CODES: Record<string, string> = {
  paper_entry_intraday_dte_not_in_band: "The contract was outside the allowed days-to-expiration window for this entry.",
  market_not_ready_for_paper_entry: "The market was not ready to open the paper trade.",
  evaluation_not_a_candidate_decision: "The bot was not in a trade setup when the open was attempted.",
  missing_contract_candidate: "No contract was selected for entry.",
  option_ask_missing_for_entry: "Option ask price was missing.",
  option_bid_missing_for_two_sided_quote: "Option bid was missing for a two-sided quote.",
  duplicate_open_position: "That contract is already open.",
  paper_entry_quantity_exceeds_small_account_max: "Quantity exceeds the paper account limit.",
  paper_entry_quantity_invalid: "Invalid quantity.",
  paper_entry_premium_exceeds_risk_budget: "Premium exceeded the risk budget.",
  paper_entry_missing_expiration_for_policy: "Expiration was missing for policy checks.",
  paper_entry_promoted_swing_dte_not_in_band: "Swing promotion window did not match the contract.",
};

export function humanizePaperTradeCode(code: string): string {
  return PAPER_CODES[code] ?? `Automatic open was blocked (${snakeToTitleCase(code)}).`;
}

/** Pull `auto_open_failed:code` tail from cycle notes and return human text, or null */
export function humanizeAutoOpenNotes(notes: string | null | undefined): string | null {
  if (!notes?.includes("auto_open_failed:")) return null;
  const part = notes.split("auto_open_failed:", 2)[1]?.split("|", 1)[0]?.trim();
  if (!part) return "Automatic open failed.";
  return humanizePaperTradeCode(part);
}

const REASONS: Record<string, string> = {
  context_live_ready: "Context is ready",
  market_and_chain_ready: "Market and option chain are ready",
  price_above_vwap: "Price is above VWAP",
  price_below_vwap: "Price is below VWAP",
  atr_positive: "Volatility (ATR) looks valid",
  call_contract_passed_quality_filters: "Call passed quality checks",
  put_contract_passed_quality_filters: "Put passed quality checks",
  contract_selected_nearest_strike_intraday_dte_band_2_5: "Contract chosen in the 2–5 day window",
  "evaluated_structural_paths:no_bull_or_bear_candidate_after_gates": "No bullish or bearish path passed the gates",
  inside_opening_range_but_vwap_disagrees_with_upper_or_lower_half: "Inside opening range but VWAP disagrees with position",
};

export function humanizeReason(reason: string): string {
  if (REASONS[reason]) return REASONS[reason];
  if (reason.startsWith("bullish_structure")) return "Bullish price structure";
  if (reason.startsWith("bearish_structure")) return "Bearish price structure";
  if (reason.startsWith("abs_price_minus_vwap")) return "Price is very close to VWAP versus ATR (chop)";
  return snakeToTitleCase(reason.replace(/=/g, " ").replace(/:/g, " "));
}

export function buildNoTradeBecauseLine(blockers: string[]): string {
  if (!blockers.length) return "No trade was taken.";
  const parts = blockers.map(humanizeBlocker);
  if (parts.length === 1) return `No trade was taken because ${lowerFirst(parts[0]!)}`;
  return `No trade was taken because: ${parts.map((p) => lowerFirst(p)).join(" Also: ")}`;
}

function lowerFirst(s: string): string {
  if (!s) return s;
  return s.charAt(0).toLowerCase() + s.slice(1);
}

const MARKET_BLOCK: Record<string, string> = {
  none: "None",
  stale_quote: "Live quote is stale",
  stale_chain: "Option chain is stale",
  startup_not_initialized: "Market data is still starting up",
};

export function humanizeMarketBlockReason(code: string | null | undefined): string {
  if (code == null || code === "" || code === "none") return "None";
  return MARKET_BLOCK[code] ?? snakeToTitleCase(code);
}

const MONITOR_STATE: Record<string, string> = {
  healthy: "Healthy — holding",
  blocked: "Watching — exit blocked",
  close_now: "Exit signal: close now",
  trail_active: "Trailing stop active",
  protected: "Stop tightened / protected",
};

export function humanizeMonitorState(state: string | null | undefined): string {
  if (state == null || state === "") return "—";
  return MONITOR_STATE[state] ?? snakeToTitleCase(state);
}

export function humanizeLimitation(line: string): string {
  const low = line.toLowerCase();
  if (low.includes("mvp")) return "Chart uses a minimal estimate, not full history.";
  if (low.includes("non-actionable") || low.includes("open-position") || low.includes("conservative")) {
    return "Some open marks were not actionable; unrealized P&L may be conservative.";
  }
  return line;
}
