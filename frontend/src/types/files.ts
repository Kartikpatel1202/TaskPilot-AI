/** Phase 5 safe downloads. Mirrors `backend/app/schemas/files.py`. No filesystem paths. */

export type DownloadStatus = "QUEUED" | "DOWNLOADING" | "VALIDATING" | "COMPLETED" | "BLOCKED" | "FAILED";

export interface DownloadedFile {
  file_id: string;
  session_id: string;
  task_id: string;
  original_name: string;
  stored_name: string;
  extension: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  source_domain: string;
  status: DownloadStatus;
  created_at: string;
  expires_at?: string | null;
  validation: string[];
}

export interface DownloadAttempt {
  status: DownloadStatus;
  message: string;
  code?: string | null;
  file?: DownloadedFile | null;
  source_domain?: string | null;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
