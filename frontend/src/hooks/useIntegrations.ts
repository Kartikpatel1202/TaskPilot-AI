"use client";

import { useCallback, useEffect, useState } from "react";

import { getCapabilities, getIntegrationStatus } from "@/lib/integrationApi";

import { useRevisionFetch } from "./useRevisionFetch";

import type { CapabilityDefinition, DomainStatusEntry } from "@/types/integration";

/** Domain statuses for this session (re-read after integration events) and the trusted capability list. */
export function useIntegrations({ sessionId, enabled, revision }: { sessionId: string | null; enabled: boolean; revision: number }) {
  const load = useCallback(() => getIntegrationStatus(sessionId as string), [sessionId]);
  const status = useRevisionFetch<DomainStatusEntry[]>(enabled && sessionId ? load : null, revision, 300);
  const [capabilities, setCapabilities] = useState<CapabilityDefinition[] | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    getCapabilities().then((c) => alive && setCapabilities(c)).catch(() => alive && setCapabilities(null));
    return () => {
      alive = false;
    };
  }, [enabled]);
  return { statuses: status.data, error: status.error, capabilities, reload: status.reload };
}
