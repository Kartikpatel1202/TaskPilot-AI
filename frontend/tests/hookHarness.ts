import { renderHook } from "@testing-library/react";

import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";

export function renderSpeechHook() {
  return renderHook(() => useSpeechRecognition({ onFinalTranscript: () => undefined }));
}
