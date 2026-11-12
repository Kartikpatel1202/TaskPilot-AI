"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { VoiceLanguage } from "@/types/voice";

export interface UseSpeechSynthesisResult {
  isSupported: boolean;
  isSpeaking: boolean;
  speak: (text: string, lang?: VoiceLanguage) => void;
  cancel: () => void;
}

function pickVoice(voices: SpeechSynthesisVoice[], lang: VoiceLanguage): SpeechSynthesisVoice | undefined {
  const exact = voices.filter((v) => v.lang.toLowerCase() === lang.toLowerCase());
  const prefix = voices.filter((v) => v.lang.toLowerCase().startsWith(lang.slice(0, 2).toLowerCase()));
  // Prefer an Indian-English or Hindi voice for Kamlesh Bhai; fall back gracefully.
  return exact.find((v) => v.localService) ?? exact[0] ?? prefix.find((v) => v.localService) ?? prefix[0];
}

/** Optional spoken feedback via the Web Speech Synthesis API (no paid services). */
export function useSpeechSynthesis({ rate = 1 }: { rate?: number } = {}): UseSpeechSynthesisResult {
  const [isSupported, setIsSupported] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const voicesRef = useRef<SpeechSynthesisVoice[]>([]);
  const rateRef = useRef(rate);
  rateRef.current = rate;

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return undefined;
    setIsSupported(true);
    const synth = window.speechSynthesis;
    const load = () => {
      voicesRef.current = synth.getVoices();
    };
    load();
    synth.addEventListener?.("voiceschanged", load);
    return () => {
      synth.removeEventListener?.("voiceschanged", load);
      synth.cancel();
    };
  }, []);

  const speak = useCallback((text: string, lang: VoiceLanguage = "en-IN") => {
    if (typeof window === "undefined" || !("speechSynthesis" in window) || !text.trim()) return;
    const synth = window.speechSynthesis;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text.slice(0, 500));
    utterance.lang = lang;
    const voice = pickVoice(voicesRef.current, lang);
    if (voice) utterance.voice = voice;
    utterance.rate = Math.min(1.5, Math.max(0.5, rateRef.current));
    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    synth.speak(utterance);
  }, []);

  const cancel = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  return { isSupported, isSpeaking, speak, cancel };
}
