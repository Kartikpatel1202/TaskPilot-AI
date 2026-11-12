"use client";

import { useCallback, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { deleteFile, fileDownloadUrl, listFiles } from "@/lib/integrationApi";

import { useRevisionFetch } from "./useRevisionFetch";

import type { DownloadedFile } from "@/types/files";

/** Validated files of this session. Deleting needs the caller's explicit confirmation first. */
export function useDownloads({ sessionId, enabled, revision }: { sessionId: string | null; enabled: boolean; revision: number }) {
  const load = useCallback(() => listFiles(sessionId as string), [sessionId]);
  const state = useRevisionFetch<DownloadedFile[]>(enabled && sessionId ? load : null, revision, 300);
  const [deleting, setDeleting] = useState<string | null>(null);
  const inFlight = useRef(false);

  const remove = useCallback(
    async (fileId: string): Promise<{ ok: boolean; error?: string }> => {
      if (!sessionId) return { ok: false, error: "No session." };
      if (inFlight.current) return { ok: false, error: "Another delete is in progress." };
      inFlight.current = true;
      setDeleting(fileId);
      try {
        await deleteFile(fileId, sessionId);
        await state.reload();
        return { ok: true };
      } catch (err) {
        return { ok: false, error: err instanceof ApiError ? err.message : "The file could not be deleted." };
      } finally {
        inFlight.current = false;
        setDeleting(null);
      }
    },
    [sessionId, state],
  );

  const urlFor = useCallback((fileId: string) => (sessionId ? fileDownloadUrl(fileId, sessionId) : "#"), [sessionId]);
  return { files: state.data, error: state.error, deleting, remove, urlFor, reload: state.reload };
}
