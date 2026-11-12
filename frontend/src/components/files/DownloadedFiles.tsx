"use client";

import { Download, FileCheck2, Loader2, ShieldCheck, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { formatBytes, type DownloadedFile } from "@/types/files";

export interface DownloadedFilesProps {
  files: DownloadedFile[];
  urlFor: (fileId: string) => string;
  deleting?: string | null;
  onDelete?: (fileId: string) => Promise<{ ok: boolean; error?: string }>;
}

/**
 * Validated downloads of this session (type, signature, size and SHA-256 checked; never opened or
 * executed by TaskPilot). Deleting is permanent and asks for an explicit second click.
 */
export function DownloadedFiles({ files, urlFor, deleting = null, onDelete }: DownloadedFilesProps) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (files.length === 0) return null;
  const remove = async (fileId: string) => {
    if (!onDelete) return;
    setError(null);
    const result = await onDelete(fileId);
    setConfirming(null);
    if (!result.ok) setError(result.error ?? "The file could not be deleted.");
  };
  return (
    <section className="flex flex-col gap-2" aria-label="Downloaded files" data-testid="downloaded-files">
      <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <ShieldCheck className="h-3 w-3" aria-hidden /> Safe downloads
      </p>
      <ul className="flex flex-col gap-1.5">
        {files.map((f) => (
          <li key={f.file_id} className="flex flex-col gap-1 rounded-md border border-white/[0.06] px-2.5 py-2 text-sm" data-testid="downloaded-file">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5"><FileCheck2 className="h-3.5 w-3.5 text-level-success" aria-hidden />{f.original_name}</span>
              <span className="text-xs text-muted-foreground">{f.extension.toUpperCase()} · {formatBytes(f.size_bytes)}</span>
            </div>
            <span className="truncate font-mono text-[10px] text-muted-foreground" title={f.sha256}>SHA-256 {f.sha256}</span>
            <span className="text-[11px] text-muted-foreground">From {f.source_domain}</span>
            <div className="flex gap-2">
              <Button asChild size="sm" variant="outline">
                <a href={urlFor(f.file_id)} download={f.original_name} rel="noopener noreferrer"><Download aria-hidden /> Save to device</a>
              </Button>
              {onDelete && (confirming === f.file_id ? (
                <>
                  <Button size="sm" variant="destructive" onClick={() => void remove(f.file_id)} disabled={deleting === f.file_id} data-testid="confirm-delete-file">
                    {deleting === f.file_id && <Loader2 className="animate-spin" aria-hidden />} Delete permanently
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>Keep</Button>
                </>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setConfirming(f.file_id)} data-testid="delete-file"><Trash2 aria-hidden /> Delete</Button>
              ))}
            </div>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
    </section>
  );
}
