/**
 * Minimal typings for the Web Speech API. The standard TypeScript DOM lib does
 * not ship SpeechRecognition types, so we declare the subset we use.
 */

export type VoiceLanguage = "en-IN" | "hi-IN" | "en-US";

export type SpeechRecognitionStatus = "idle" | "starting" | "listening" | "stopping" | "error";

export type SpeechRecognitionErrorKind =
  | "unsupported"
  | "permission-denied"
  | "no-microphone"
  | "no-speech"
  | "network"
  | "aborted"
  | "unknown";

export interface SpeechRecognitionAlternativeLike {
  readonly transcript: string;
  readonly confidence: number;
}

export interface SpeechRecognitionResultLike {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}

export interface SpeechRecognitionResultListLike {
  readonly length: number;
  [index: number]: SpeechRecognitionResultLike;
}

export interface SpeechRecognitionEventLike extends Event {
  readonly resultIndex: number;
  readonly results: SpeechRecognitionResultListLike;
}

export interface SpeechRecognitionErrorEventLike extends Event {
  readonly error: string;
  readonly message?: string;
}

export interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onstart: ((this: SpeechRecognitionLike, ev: Event) => unknown) | null;
  onend: ((this: SpeechRecognitionLike, ev: Event) => unknown) | null;
  onresult: ((this: SpeechRecognitionLike, ev: SpeechRecognitionEventLike) => unknown) | null;
  onerror: ((this: SpeechRecognitionLike, ev: SpeechRecognitionErrorEventLike) => unknown) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

export type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

export interface SpeechRecognitionState {
  isSupported: boolean;
  status: SpeechRecognitionStatus;
  isListening: boolean;
  interimTranscript: string;
  error: { kind: SpeechRecognitionErrorKind; message: string } | null;
  language: VoiceLanguage;
}

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  }
}
