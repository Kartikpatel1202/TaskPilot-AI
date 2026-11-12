/** Settings page: the signed-in user's preferences (one local profile when sign-in is off). */

import { z } from "zod";

import { request } from "./api";

export type LanguagePreference = "auto" | "en" | "hinglish" | "hi";

export interface UserPreferences {
  display_name: string;
  language: LanguagePreference;
  voice_input_enabled: boolean;
  voice_output_enabled: boolean;
  voice_auto_submit: boolean;
  voice_auto_execute: boolean;
  voice_continuous: boolean;
  speech_rate: number;
  preferred_store: "none" | "blinkit" | "amazon";
}

export const DEFAULT_PREFERENCES: UserPreferences = {
  display_name: "",
  language: "auto",
  voice_input_enabled: true,
  voice_output_enabled: true,
  voice_auto_submit: true,
  voice_auto_execute: true,
  voice_continuous: true,
  speech_rate: 1,
  preferred_store: "none",
};

const preferencesSchema: z.ZodType<UserPreferences> = z.object({
  display_name: z.string().max(40),
  language: z.enum(["auto", "en", "hinglish", "hi"]),
  voice_input_enabled: z.boolean(),
  voice_output_enabled: z.boolean(),
  voice_auto_submit: z.boolean(),
  voice_auto_execute: z.boolean(),
  voice_continuous: z.boolean(),
  speech_rate: z.number().min(0.5).max(1.5),
  preferred_store: z.enum(["none", "blinkit", "amazon"]),
});

export const getPreferences = () => request<UserPreferences>("/preferences", { schema: preferencesSchema });

export const updatePreferences = (patch: Partial<UserPreferences>) =>
  request<UserPreferences>("/preferences", { method: "PUT", body: patch, schema: preferencesSchema });
