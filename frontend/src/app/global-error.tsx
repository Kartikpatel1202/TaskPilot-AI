"use client";

/** Last-resort boundary for errors in the root layout itself. */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en" className="dark">
      <body style={{ fontFamily: "system-ui", padding: 32, background: "#05070d", color: "#e5e7eb" }}>
        <main role="alert">
          <h1>TaskPilot AI could not load.</h1>
          <p>Your tasks are stored on the server. Please reload.</p>
          <button type="button" onClick={reset}>Reload</button>
        </main>
      </body>
    </html>
  );
}
