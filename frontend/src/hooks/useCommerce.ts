"use client";

import { useCallback, useEffect, useRef, type Dispatch } from "react";

import { ApiError } from "@/lib/api";
import {
  getShoppingSummary,
  refreshCart as refreshCartRequest,
  reviewCheckout as reviewCheckoutRequest,
  selectProduct as selectProductRequest,
  updateCartQuantity,
} from "@/lib/commerceApi";

import type { TaskPilotAction } from "@/context/taskPilotReducer";

export interface CommerceCommandResult {
  ok: boolean;
  error?: string;
}

interface UseCommerceOptions {
  sessionId: string | null;
  taskId: string | null;
  /** The active plan contains commerce steps and has been run at least once. */
  enabled: boolean;
  /** Bumped by every commerce.* telemetry event for the active task. */
  revision: number;
  dispatch: Dispatch<TaskPilotAction>;
}

const message = (error: unknown, fallback: string) => (error instanceof ApiError ? error.message : fallback);

/**
 * Keeps the active task's shopping summary in sync with the backend (re-fetched after every
 * commerce event) and exposes the user's commerce actions. Purchases are never triggered here.
 */
export function useCommerce({ sessionId, taskId, enabled, revision, dispatch }: UseCommerceOptions) {
  const inFlight = useRef(false);

  const reload = useCallback(async () => {
    if (!sessionId || !taskId) return;
    try {
      dispatch({ type: "COMMERCE_SUMMARY_LOADED", summary: await getShoppingSummary(taskId, sessionId) });
    } catch {
      // 404 until the first commerce step runs — nothing to show yet, nothing invented.
    }
  }, [sessionId, taskId, dispatch]);

  useEffect(() => {
    if (!enabled) return undefined;
    const timer = setTimeout(() => void reload(), 200); // coalesce bursts of events
    return () => clearTimeout(timer);
  }, [enabled, revision, reload]);

  const guarded = useCallback(
    async (work: () => Promise<unknown>, fallback: string): Promise<CommerceCommandResult> => {
      if (!sessionId || !taskId) return { ok: false, error: "No active shopping task." };
      if (inFlight.current) return { ok: false, error: "Another request is already in progress." };
      inFlight.current = true;
      try {
        await work();
        await reload();
        return { ok: true };
      } catch (error) {
        return { ok: false, error: message(error, fallback) };
      } finally {
        inFlight.current = false;
      }
    },
    [sessionId, taskId, reload],
  );

  const chooseProduct = useCallback(
    (selectionId: string, candidateId: string | null) =>
      guarded(() => selectProductRequest(taskId as string, sessionId as string, selectionId, candidateId), "Your choice could not be sent."),
    [guarded, taskId, sessionId],
  );
  const refreshCart = useCallback(() => guarded(() => refreshCartRequest(sessionId as string), "The cart could not be refreshed."), [guarded, sessionId]);
  const changeQuantity = useCallback(
    (itemId: string, quantity: number) =>
      guarded(() => updateCartQuantity(sessionId as string, itemId, quantity), "The quantity could not be changed."),
    [guarded, sessionId],
  );
  const reviewCheckout = useCallback(
    () => guarded(() => reviewCheckoutRequest(taskId as string, sessionId as string), "Checkout could not be reviewed."),
    [guarded, taskId, sessionId],
  );

  return { reload, chooseProduct, refreshCart, changeQuantity, reviewCheckout };
}
