/**
 * Live browser stream protocol (binary WebSocket, separate from telemetry).
 *
 * Packet: 4-byte big-endian metadata length | UTF-8 JSON metadata | JPEG bytes.
 * Text messages are small JSON control messages (stream.ready, pong, stream.ended, error).
 * Parsing is strict and never throws: anything malformed is reported and dropped.
 */

import { z } from "zod";

import { API_PREFIX } from "./constants";

import type { FrameMetadata, StreamControlMessage } from "@/types/browser";

export const MAX_METADATA_BYTES = 4096;
export const DEFAULT_MAX_FRAME_BYTES = 2_000_000;
const JPEG_MAGIC = [0xff, 0xd8, 0xff] as const;

const uuid = z.string().uuid();

export const frameMetadataSchema: z.ZodType<FrameMetadata> = z.object({
  frame_id: uuid,
  session_id: uuid,
  task_id: uuid.nullable(),
  sequence: z.number().int().positive(),
  captured_at: z.string().datetime({ offset: true }),
  mime_type: z.literal("image/jpeg"),
  width: z.number().int().positive().max(10_000),
  height: z.number().int().positive().max(10_000),
});

const controlSchema: z.ZodType<StreamControlMessage> = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("stream.ready"),
    session_id: uuid,
    format: z.literal("jpeg"),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    status: z.enum(["live", "waiting"]),
    max_fps: z.number().positive().max(5),
  }),
  z.object({ type: z.literal("pong") }),
  z.object({ type: z.literal("stream.ended"), reason: z.string().max(500) }),
  z.object({ type: z.literal("error"), code: z.string().max(80), message: z.string().max(500) }),
]);

export type FrameParseResult =
  | { ok: true; meta: FrameMetadata; jpeg: Uint8Array<ArrayBuffer> }
  | { ok: false; reason: string };

/** Parse one binary packet. `expectedSessionId` enforces per-session isolation on the client too. */
export function parseFramePacket(
  buffer: ArrayBuffer,
  { expectedSessionId, maxFrameBytes = DEFAULT_MAX_FRAME_BYTES }: { expectedSessionId?: string; maxFrameBytes?: number } = {},
): FrameParseResult {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 6) return { ok: false, reason: "Packet too short" };
  const view = new DataView(buffer);
  const length = view.getUint32(0, false);
  if (length === 0 || length > MAX_METADATA_BYTES || 4 + length >= buffer.byteLength) {
    return { ok: false, reason: "Invalid metadata length" };
  }
  let json: unknown;
  try {
    json = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(buffer, 4, length)));
  } catch {
    return { ok: false, reason: "Metadata is not valid JSON" };
  }
  const meta = frameMetadataSchema.safeParse(json);
  if (!meta.success) return { ok: false, reason: "Invalid frame metadata" };
  if (expectedSessionId && meta.data.session_id !== expectedSessionId) {
    return { ok: false, reason: "Frame belongs to another session" };
  }
  const jpeg = new Uint8Array(buffer, 4 + length);
  if (jpeg.byteLength > maxFrameBytes) return { ok: false, reason: "Frame exceeds the maximum size" };
  if (!JPEG_MAGIC.every((byte, i) => jpeg[i] === byte)) return { ok: false, reason: "Frame is not a JPEG" };
  return { ok: true, meta: meta.data, jpeg };
}

export type ControlParseResult = { ok: true; message: StreamControlMessage } | { ok: false; reason: string };

export function parseStreamControl(raw: string): ControlParseResult {
  if (raw.length > 4096) return { ok: false, reason: "Control message too long" };
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch {
    return { ok: false, reason: "Invalid JSON" };
  }
  const parsed = controlSchema.safeParse(json);
  return parsed.success ? { ok: true, message: parsed.data } : { ok: false, reason: "Unrecognised control message" };
}

/** True when `next` should replace the currently shown frame (drops stale/out-of-order frames). */
export function isNewerFrame(current: FrameMetadata | null, next: FrameMetadata): boolean {
  return current === null || current.session_id !== next.session_id || next.sequence > current.sequence;
}

export function buildBrowserStreamUrl(wsBase: string, sessionId: string): string {
  return `${wsBase.replace(/\/+$/, "")}${API_PREFIX}/browser/sessions/${encodeURIComponent(sessionId)}/stream`;
}
