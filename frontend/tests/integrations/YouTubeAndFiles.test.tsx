import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CalendarEventReview } from "@/components/calendar/CalendarEventReview";
import { DownloadedFiles } from "@/components/files/DownloadedFiles";
import { YouTubeResults } from "@/components/youtube/YouTubeResults";
import { formatBytes } from "@/types/files";

import { uuidFor } from "../fixtures";
import { calendarReview, downloadedFile, youtubeResults } from "./integrationFixtures";

describe("YouTubeResults", () => {
  it("marks the selected video and the verified playback state", () => {
    render(<YouTubeResults data={youtubeResults()} />);
    const rows = screen.getAllByTestId("youtube-result");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("playback-state")).toHaveTextContent("Playing (verified)");
    expect(screen.getByRole("link", { name: /Open “Python Tutorial/ })).toHaveAttribute("rel", "noopener noreferrer nofollow");
  });

  it("never claims playback that was not verified", () => {
    render(<YouTubeResults data={youtubeResults({ playback: { state: "PLAYBACK_BLOCKED", message: "YouTube says: Video unavailable", observed_at: "2026-11-09T10:00:00Z" } })} />);
    expect(screen.getByTestId("playback-state")).toHaveTextContent("Blocked by YouTube");
    expect(screen.getByTestId("playback-message")).toHaveTextContent("Video unavailable");
  });
});

describe("DownloadedFiles", () => {
  it("shows validated metadata and asks before deleting", async () => {
    const onDelete = vi.fn().mockResolvedValue({ ok: true });
    render(<DownloadedFiles files={[downloadedFile()]} urlFor={(id) => `/api/v1/files/${id}/download?session_id=s`} onDelete={onDelete} />);
    const row = screen.getByTestId("downloaded-file");
    expect(row).toHaveTextContent("report.pdf");
    expect(row).toHaveTextContent("PDF · 409 B");
    expect(row).toHaveTextContent(`SHA-256 ${"b".repeat(64)}`);
    expect(row).not.toHaveTextContent(/[A-Z]:\\|\/runtime\//); // never a filesystem path
    expect(screen.getByRole("link", { name: /save to device/i })).toHaveAttribute("href", `/api/v1/files/${uuidFor(900)}/download?session_id=s`);
    await userEvent.click(screen.getByTestId("delete-file"));
    expect(onDelete).not.toHaveBeenCalled(); // first click only asks
    await userEvent.click(screen.getByTestId("confirm-delete-file"));
    expect(onDelete).toHaveBeenCalledWith(uuidFor(900));
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});

describe("CalendarEventReview", () => {
  it("shows the verified event with its exact time and timezone", () => {
    render(<CalendarEventReview review={calendarReview()} />);
    expect(screen.getByTestId("calendar-status")).toHaveTextContent("Created (verified)");
    expect(screen.getByTestId("calendar-time")).toHaveTextContent("3:00 PM – 3:30 PM (30 min)");
  });

  it("an unverifiable creation is shown as unknown", () => {
    render(<CalendarEventReview review={calendarReview({ status: "UNKNOWN", message: "Please check Google Calendar before trying again." })} />);
    expect(screen.getByTestId("calendar-status")).toHaveTextContent("Unknown — please check");
  });
});
