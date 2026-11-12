import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useBrowserStream } from "@/hooks/useBrowserStream";
import {
  buildBrowserStreamUrl,
  isNewerFrame,
  parseFramePacket,
  parseStreamControl,
} from "@/lib/browserStream";

import { SESSION, uuidFor } from "../fixtures";

import type { FrameMetadata } from "@/types/browser";

const JPEG = new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0, 0, 0, 0xff, 0xd9]);

function meta(overrides: Partial<FrameMetadata> = {}): FrameMetadata {
  return {
    frame_id: uuidFor(1),
    session_id: SESSION,
    task_id: null,
    sequence: 1,
    captured_at: "2026-11-05T10:00:00.000000+00:00",
    mime_type: "image/jpeg",
    width: 1440,
    height: 900,
    ...overrides,
  };
}

function packet(m: unknown, image: Uint8Array = JPEG, lengthOverride?: number): ArrayBuffer {
  const body = new TextEncoder().encode(typeof m === "string" ? m : JSON.stringify(m));
  const out = new Uint8Array(4 + body.length + image.length);
  new DataView(out.buffer).setUint32(0, lengthOverride ?? body.length, false);
  out.set(body, 4);
  out.set(image, 4 + body.length);
  return out.buffer;
}

describe("parseFramePacket", () => {
  it("parses a valid packet (big-endian length + JSON + JPEG)", () => {
    const result = parseFramePacket(packet(meta({ sequence: 7 })), { expectedSessionId: SESSION });
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.meta.sequence).toBe(7);
      expect(Array.from(result.jpeg.slice(0, 3))).toEqual([0xff, 0xd8, 0xff]);
    }
  });

  it.each([
    ["too short", new Uint8Array([0, 0, 0]).buffer],
    ["zero length", packet(meta(), JPEG, 0)],
    ["length past the end", packet(meta(), JPEG, 100_000)],
    ["metadata is not JSON", packet("not json!")],
    ["metadata missing fields", packet({ sequence: 1 })],
    ["wrong mime type", packet({ ...meta(), mime_type: "image/png" })],
  ])("rejects a malformed packet: %s", (_label, buffer) => {
    expect(parseFramePacket(buffer as ArrayBuffer).ok).toBe(false);
  });

  it("rejects non-JPEG and oversized images", () => {
    expect(parseFramePacket(packet(meta(), new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2]))).ok).toBe(false);
    expect(parseFramePacket(packet(meta()), { maxFrameBytes: 4 }).ok).toBe(false);
  });

  it("rejects frames of another session (client-side isolation)", () => {
    const result = parseFramePacket(packet(meta({ session_id: uuidFor(99) })), { expectedSessionId: SESSION });
    expect(result).toEqual({ ok: false, reason: "Frame belongs to another session" });
  });
});

describe("stream helpers", () => {
  it("only accepts strictly newer frames of the same session", () => {
    expect(isNewerFrame(null, meta())).toBe(true);
    expect(isNewerFrame(meta({ sequence: 5 }), meta({ sequence: 6 }))).toBe(true);
    expect(isNewerFrame(meta({ sequence: 5 }), meta({ sequence: 5 }))).toBe(false);
    expect(isNewerFrame(meta({ sequence: 5 }), meta({ sequence: 3 }))).toBe(false);
  });

  it("validates control messages", () => {
    const ready = parseStreamControl(
      JSON.stringify({ type: "stream.ready", session_id: SESSION, format: "jpeg", width: 1440, height: 900, status: "live", max_fps: 1 }),
    );
    expect(ready.ok && ready.message.type).toBe("stream.ready");
    expect(parseStreamControl(JSON.stringify({ type: "pong" })).ok).toBe(true);
    expect(parseStreamControl(JSON.stringify({ type: "stream.ready", max_fps: 60 })).ok).toBe(false);
    expect(parseStreamControl("{oops").ok).toBe(false);
  });

  it("builds the per-session stream URL", () => {
    expect(buildBrowserStreamUrl("ws://localhost:8000/", SESSION)).toBe(`ws://localhost:8000/api/v1/browser/sessions/${SESSION}/stream`);
  });
});

// ------------------------------------------------------------------ hook with a fake socket

class FakeSocket {
  static instances: FakeSocket[] = [];
  binaryType = "blob";
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  receive(data: unknown) {
    this.onmessage?.({ data } as MessageEvent);
  }
}

describe("useBrowserStream", () => {
  let created: string[];
  let revoked: string[];

  beforeEach(() => {
    FakeSocket.instances = [];
    created = [];
    revoked = [];
    let n = 0;
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: () => {
        const url = `blob:frame-${++n}`;
        created.push(url);
        return url;
      },
      revokeObjectURL: (url: string) => revoked.push(url),
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function setup(enabled = true) {
    return renderHook(() =>
      useBrowserStream({ sessionId: SESSION, enabled, wsBase: "ws://test", createSocket: (u) => new FakeSocket(u) as unknown as WebSocket }),
    );
  }

  it("does not connect while disabled", () => {
    const { result } = setup(false);
    expect(FakeSocket.instances).toHaveLength(0);
    expect(result.current.status).toBe("idle");
  });

  it("subscribes, shows the newest frame and drops stale / foreign / malformed ones", () => {
    const { result } = setup();
    const socket = FakeSocket.instances[0]!;
    expect(socket.url).toBe(`ws://test/api/v1/browser/sessions/${SESSION}/stream`);
    act(() => socket.open());
    expect(socket.binaryType).toBe("arraybuffer");
    expect(JSON.parse(socket.sent[0]!)).toEqual({ type: "subscribe" });

    act(() =>
      socket.receive(JSON.stringify({ type: "stream.ready", session_id: SESSION, format: "jpeg", width: 1440, height: 900, status: "waiting", max_fps: 1 })),
    );
    expect(result.current.status).toBe("waiting");

    act(() => socket.receive(packet(meta({ sequence: 2 }))));
    expect(result.current.status).toBe("live");
    expect(result.current.frame?.meta.sequence).toBe(2);
    expect(result.current.frame?.url).toBe("blob:frame-1");

    act(() => socket.receive(packet(meta({ sequence: 1 })))); // stale
    act(() => socket.receive(packet(meta({ sequence: 3, session_id: uuidFor(42) })))); // other session
    act(() => socket.receive(packet("garbage")));
    expect(result.current.frame?.meta.sequence).toBe(2);
    expect(result.current.droppedFrames).toBe(3);

    act(() => socket.receive(packet(meta({ sequence: 4 }))));
    expect(result.current.frame?.meta.sequence).toBe(4);
    expect(revoked).toContain("blob:frame-1"); // only the latest frame is kept in memory
  });

  it("revokes the frame and closes the socket on unmount", () => {
    const { unmount } = setup();
    const socket = FakeSocket.instances[0]!;
    act(() => socket.open());
    act(() => socket.receive(packet(meta({ sequence: 1 }))));
    unmount();
    expect(revoked).toContain(created[0]);
    expect(socket.readyState).toBe(3);
  });

  it("reconnects with backoff after an unexpected close", () => {
    vi.useFakeTimers();
    try {
      const { result } = setup();
      const first = FakeSocket.instances[0]!;
      act(() => first.open());
      act(() => first.onclose?.());
      expect(result.current.status).toBe("reconnecting");
      act(() => vi.advanceTimersByTime(2_000));
      expect(FakeSocket.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
