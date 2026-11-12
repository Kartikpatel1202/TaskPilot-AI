import type { Language } from "@/types/telemetry";
import type { VoiceLanguage } from "@/types/voice";

/**
 * Kamlesh Bhai — TaskPilot AI's assistant persona.
 * Friendly, sharp, a little witty, always reliable. Mirrors the user's language:
 * English → English, Hindi → Hindi, Hinglish → Hinglish. The backend detects the
 * language and tags assistant replies; the UI picks a matching voice.
 */
export const ASSISTANT_NAME = "Kamlesh Bhai";
export const PRODUCT_NAME = "TaskPilot AI";

export function speechLangFor(language: Language | null | undefined): VoiceLanguage {
  return language === "hi" ? "hi-IN" : "en-IN";
}

export const VOICE_LANGUAGE_OPTIONS: ReadonlyArray<{ value: VoiceLanguage; label: string; short: string }> = [
  { value: "en-IN", label: "English / Hinglish", short: "EN" },
  { value: "hi-IN", label: "हिन्दी (Hindi)", short: "हि" },
];
