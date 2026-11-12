import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { CommandInput, type CommandInputProps } from "@/components/command/CommandInput";
import { MAX_COMMAND_LENGTH } from "@/lib/constants";

function Harness(props: Partial<CommandInputProps> & { initial?: string; onSubmitSpy?: (v: string) => void }) {
  const { initial = "", onSubmitSpy = () => undefined, ...rest } = props;
  const [value, setValue] = useState(initial);
  return <CommandInput value={value} onChange={setValue} onSubmit={onSubmitSpy} {...rest} />;
}

const textbox = () => screen.getByRole("textbox", { name: /command for taskpilot/i });
const executeButton = () => screen.getByRole("button", { name: /execute/i });

describe("CommandInput", () => {
  it("renders the placeholder and accepts typed text", async () => {
    render(<Harness />);
    expect(textbox()).toHaveAttribute("placeholder", "Ask TaskPilot to do something...");
    await userEvent.type(textbox(), "Open YouTube");
    expect(textbox()).toHaveValue("Open YouTube");
  });

  it("submits a valid, trimmed command when Execute is clicked", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmitSpy={onSubmit} />);
    await userEvent.type(textbox(), "  Find a laptop under ₹60,000  ");
    await userEvent.click(executeButton());
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("Find a laptop under ₹60,000");
  });

  it("submits on Enter", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmitSpy={onSubmit} />);
    await userEvent.type(textbox(), "Draft an email{Enter}");
    expect(onSubmit).toHaveBeenCalledWith("Draft an email");
    expect(textbox()).toHaveValue("Draft an email"); // Enter did not insert a newline
  });

  it("does not submit an empty or whitespace-only command", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmitSpy={onSubmit} />);
    expect(executeButton()).toBeDisabled();
    await userEvent.type(textbox(), "   ");
    expect(executeButton()).toBeDisabled();
    await userEvent.type(textbox(), "{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("inserts a newline on Shift+Enter instead of submitting", async () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmitSpy={onSubmit} />);
    await userEvent.type(textbox(), "line one{Shift>}{Enter}{/Shift}line two");
    expect(textbox()).toHaveValue("line one\nline two");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("enforces the 4,000 character limit", () => {
    render(<Harness />);
    expect(textbox()).toHaveAttribute("maxLength", String(MAX_COMMAND_LENGTH));
    fireEvent.change(textbox(), { target: { value: "a".repeat(MAX_COMMAND_LENGTH + 250) } });
    expect((textbox() as HTMLTextAreaElement).value).toHaveLength(MAX_COMMAND_LENGTH);
    expect(screen.getByTestId("char-count")).toHaveTextContent("4,000/4,000");
  });

  it("disables Execute when the backend is unavailable", async () => {
    const onSubmit = vi.fn();
    render(<Harness initial="Open Blinkit" disabled disabledReason="Backend connection unavailable" onSubmitSpy={onSubmit} />);
    expect(executeButton()).toBeDisabled();
    // typing is still possible while offline
    await userEvent.type(textbox(), " now");
    expect(textbox()).toHaveValue("Open Blinkit now");
    await userEvent.type(textbox(), "{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows a loading state and blocks resubmission while submitting", async () => {
    const onSubmit = vi.fn();
    render(<Harness initial="Open Blinkit" isSubmitting onSubmitSpy={onSubmit} />);
    const button = screen.getByRole("button", { name: /sending/i });
    expect(button).toBeDisabled();
    await userEvent.type(textbox(), "{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows interim speech text and errors", () => {
    render(<Harness interimText="open you" error="Something failed" />);
    expect(screen.getByTestId("interim-transcript")).toHaveTextContent("open you");
    expect(screen.getByRole("alert")).toHaveTextContent("Something failed");
  });
});
