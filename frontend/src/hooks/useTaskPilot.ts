"use client";

import { useContext } from "react";

import {
  TaskPilotActionsContext,
  TaskPilotStateContext,
  TaskPilotUiContext,
  type TaskPilotActions,
  type TaskPilotUi,
} from "@/context/TaskPilotContext";

import type { TaskPilotState } from "@/context/taskPilotReducer";

function required<T>(value: T | null, name: string): T {
  if (value === null) throw new Error(`${name} must be used inside <TaskPilotProvider>.`);
  return value;
}

export function useTaskPilotState(): TaskPilotState {
  return required(useContext(TaskPilotStateContext), "useTaskPilotState");
}

export function useTaskPilotActions(): TaskPilotActions {
  return required(useContext(TaskPilotActionsContext), "useTaskPilotActions");
}

export function useTaskPilotUi(): TaskPilotUi {
  return required(useContext(TaskPilotUiContext), "useTaskPilotUi");
}

/** Convenience hook returning state, actions and UI flags together. */
export function useTaskPilot(): { state: TaskPilotState; actions: TaskPilotActions; ui: TaskPilotUi } {
  return { state: useTaskPilotState(), actions: useTaskPilotActions(), ui: useTaskPilotUi() };
}
