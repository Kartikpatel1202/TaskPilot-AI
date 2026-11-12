"use client";

import { Power, RefreshCw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import type { StreamStatus } from "@/types/browser";

interface BrowserControlsProps {
  streamStatus: StreamStatus;
  /** A browser exists for this session and no plan is running in it. */
  canClose: boolean;
  onReconnect: () => void;
  onClose: () => Promise<unknown>;
}

/** Preview controls only — they never navigate or click on a website. */
export function BrowserControls({ streamStatus, canClose, onReconnect, onClose }: BrowserControlsProps) {
  const [confirming, setConfirming] = useState(false);
  const [closing, setClosing] = useState(false);
  const showReconnect = streamStatus === "error" || streamStatus === "ended";

  const close = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setClosing(true);
    try {
      await onClose();
    } finally {
      setClosing(false);
      setConfirming(false);
    }
  };

  if (!showReconnect && !canClose) return null;
  return (
    <div className="flex items-center gap-1.5">
      {showReconnect && (
        <Button size="sm" variant="ghost" onClick={onReconnect}>
          <RefreshCw aria-hidden /> Reconnect preview
        </Button>
      )}
      {canClose && (
        <Button
          size="sm"
          variant={confirming ? "destructive" : "ghost"}
          onClick={close}
          onBlur={() => setConfirming(false)}
          disabled={closing}
          aria-label={confirming ? "Confirm closing the browser" : "Close browser"}
        >
          <Power aria-hidden /> {confirming ? "Confirm close" : "Close browser"}
        </Button>
      )}
    </div>
  );
}
