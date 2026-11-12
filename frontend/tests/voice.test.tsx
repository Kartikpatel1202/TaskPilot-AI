import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CommandInput } from "@/components/command/CommandInput";
import { VoiceButton } from "@/components/command/VoiceButton";
import { VoiceStatus } from "@/components/command/VoiceStatus";
import { useSpeechRecognition } from "@/hooks/useSpeechRecognition";

import type { SpeechRecognitionErrorEventLike, SpeechRecognitionEventLike, SpeechRecognitionLike } from "@/types/voice";

/** Minimal mock of the Web Speech API recognition object — no microphone needed. */
class MockRecognition extends EventTarget implements SpeechRecognitionLike {
  static instances: MockRecognition[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  maxAlternatives = 1;
  onstart: SpeechRecognitionLike["onstart"] = null;
  onend: SpeechRecognitionLike["onend"] = null;
  onresult: SpeechRecognitionLike["onresult"] = null;
  onerror: SpeechRecognitionLike["onerror"] = null;
  start = vi.fn(() => this.onstart?.call(this, new Event("start")));
  stop = vi.fn(() => this.onend?.call(this, new Event("end")));
  abort = vi.fn();

  constructor() {
    super();
    MockRecognition.instances.push(this);
  }

  emitResult(transcript: string, isFinal: boolean) {
    const result = Object.assign([{ transcript, confidence: 0.9 }], { isFinal });
    const event = Object.assign(new Event("result"), { resultIndex: 0, results: [result] });
    this.onresult?.call(this, event as unknown as SpeechRecognitionEventLike);
  }

  emitError(error: string) {
    this.onerror?.call(this, Object.assign(new Event("error"), { error }) as SpeechRecognitionErrorEventLike);
    this.onend?.call(this, new Event("end"));
  }
}

function VoiceHarness({ onSubmit }: { onSubmit: (v: string) => void }) {
  const [value, setValue] = useState("");
  const speech = useSpeechRecognition({ onFinalTranscript: (t) => setValue((p) => (p ? `${p} ${t}` : t)) });
  return (
    <>
      <CommandInput
        value={value}
        onChange={setValue}
        onSubmit={onSubmit}
        interimText={speech.interimTranscript}
        actions={<VoiceButton isListening={speech.isListening} isSupported={speech.isSupported} onToggle={speech.toggle} />}
      />
      <VoiceStatus state={speech} onLanguageChange={speech.setLanguage} onDismissError={speech.clearError} />
    </>
  );
}

describe("voice input (mocked Web Speech API)", () => {
  beforeEach(() => {
    MockRecognition.instances = [];
    (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition = MockRecognition;
  });
  afterEach(() => {
    delete (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
  });

  it("starts and stops recording on microphone clicks", async () => {
    render(<VoiceHarness onSubmit={vi.fn()} />);
    const mic = await screen.findByRole("button", { name: /start voice input/i });
    await userEvent.click(mic);
    expect(MockRecognition.instances).toHaveLength(1);
    expect(MockRecognition.instances[0]?.lang).toBe("en-IN");
    expect(screen.getByRole("button", { name: /stop voice input/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/listening/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /stop voice input/i }));
    expect(MockRecognition.instances[0]?.stop).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /start voice input/i })).toBeInTheDocument();
  });

  it("shows interim text and populates the final transcript without submitting", async () => {
    const onSubmit = vi.fn();
    render(<VoiceHarness onSubmit={onSubmit} />);
    await userEvent.click(await screen.findByRole("button", { name: /start voice input/i }));
    const rec = MockRecognition.instances[0]!;
    act(() => rec.emitResult("blinkit kholo", false));
    expect(screen.getByTestId("interim-transcript")).toHaveTextContent("blinkit kholo");
    act(() => rec.emitResult("Blinkit kholo aur doodh add karo", true));
    expect(screen.getByRole("textbox")).toHaveValue("Blinkit kholo aur doodh add karo");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("prevents multiple simultaneous recognition instances", async () => {
    const { result } = await import("./hookHarness").then((m) => m.renderSpeechHook());
    act(() => result.current.start());
    act(() => result.current.start());
    expect(MockRecognition.instances).toHaveLength(1);
  });

  it("reports permission-denied errors", async () => {
    render(<VoiceHarness onSubmit={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /start voice input/i }));
    act(() => MockRecognition.instances[0]!.emitError("not-allowed"));
    expect(screen.getByRole("alert")).toHaveTextContent(/microphone permission was denied/i);
  });

  it("reports microphone access errors", async () => {
    render(<VoiceHarness onSubmit={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /start voice input/i }));
    act(() => MockRecognition.instances[0]!.emitError("audio-capture"));
    expect(screen.getByRole("alert")).toHaveTextContent(/no microphone/i);
  });

  it("aborts recognition on unmount", async () => {
    const { unmount } = render(<VoiceHarness onSubmit={vi.fn()} />);
    await userEvent.click(await screen.findByRole("button", { name: /start voice input/i }));
    unmount();
    expect(MockRecognition.instances[0]?.abort).toHaveBeenCalled();
  });

  it("shows an unsupported-browser message when the API is missing", () => {
    delete (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
    render(<VoiceHarness onSubmit={vi.fn()} />);
    expect(screen.getByRole("button", { name: /not supported/i })).toBeDisabled();
    expect(screen.getByText(/isn't supported in this browser/i)).toBeInTheDocument();
  });

  it("uses Hindi recognition when हि is selected", async () => {
    render(<VoiceHarness onSubmit={vi.fn()} />);
    await userEvent.click(await screen.findByRole("radio", { name: /हि/ }));
    await userEvent.click(screen.getByRole("button", { name: /start voice input/i }));
    expect(MockRecognition.instances[0]?.lang).toBe("hi-IN");
  });
});
