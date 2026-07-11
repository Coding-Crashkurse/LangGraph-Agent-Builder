/** Server config (SPEC §18.1: LAB_AUTO_SAVING / LAB_AUTO_SAVING_INTERVAL_MS)
 * via the typed openapi-fetch client — no hand-rolled fetch (SPEC §11.2). */

import { useQuery } from "@tanstack/react-query";

import { ApiError, raw } from "@/api/client";

export interface ServerConfig {
  auto_saving: boolean;
  auto_saving_interval_ms: number;
}

const DEFAULTS: ServerConfig = { auto_saving: false, auto_saving_interval_ms: 1000 };

export async function fetchServerConfig(): Promise<ServerConfig> {
  const result = await raw.GET("/api/v1/config");
  if (result.error !== undefined || !result.response.ok) {
    throw new ApiError(result.response.status, result.response.statusText);
  }
  const cfg = (result.data ?? {}) as Record<string, unknown>;
  return {
    auto_saving: Boolean(cfg.auto_saving),
    auto_saving_interval_ms:
      Number(cfg.auto_saving_interval_ms) || DEFAULTS.auto_saving_interval_ms,
  };
}

/** Autosave settings; falls back to safe defaults while loading / on error. */
export function useServerConfig(): ServerConfig {
  const query = useQuery({
    queryKey: ["server-config"],
    queryFn: fetchServerConfig,
    staleTime: 60_000,
  });
  return query.data ?? DEFAULTS;
}
