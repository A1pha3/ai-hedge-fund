/**
 * Characterization tests for AttributionPage (R29 — UX V-3 fix).
 *
 * V-3 (ux-best-practices-2025-2026.md L44): the demo trigger was a raw
 * `<button>` with hardcoded `bg-blue-600` colors that ignore the design
 * tokens (theme-broken). It is now a shadcn `<Button>` (default variant),
 * which renders `bg-primary` + `text-primary-foreground` and inherits the
 * focus-ring + disabled treatment shared by every other button in the app.
 *
 * These tests pin the user-observable contract:
 * - The trigger is rendered as a `<button>` element with role/name "Run Demo Attribution".
 * - It uses the design-token classes from the shadcn Button default variant
 *   (`bg-primary`, `text-primary-foreground`) instead of the previous
 *   hardcoded `bg-blue-600` / `bg-blue-700` palette.
 * - It does NOT carry the previously hardcoded `bg-blue-600` / `bg-blue-700`
 *   classes (regression guard against accidental revert).
 * - Standard shadcn Button focus-ring class is present.
 * - The `mb-6` layout spacing the page composes with is preserved.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../services/attribution-api", () => ({
  fetchAttribution: vi.fn(),
}));

import AttributionPage from "./AttributionPage";

describe("AttributionPage demo trigger (V-3)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the demo trigger as a <button> with the expected accessible name", () => {
    render(<AttributionPage />);
    const btn = screen.getByRole("button", { name: /run demo attribution/i });
    expect(btn).toBeInTheDocument();
    expect(btn.tagName).toBe("BUTTON");
  });

  it("uses shadcn Button design-token classes instead of hardcoded colors", () => {
    render(<AttributionPage />);
    const btn = screen.getByRole("button", { name: /run demo attribution/i });
    // shadcn Button default variant
    expect(btn.className).toContain("bg-primary");
    expect(btn.className).toContain("text-primary-foreground");
  });

  it("regression guard: no hardcoded bg-blue-600 / bg-blue-700 (V-3 source palette)", () => {
    render(<AttributionPage />);
    const btn = screen.getByRole("button", { name: /run demo attribution/i });
    expect(btn.className).not.toContain("bg-blue-600");
    expect(btn.className).not.toContain("bg-blue-700");
  });

  it("preserves the focus-visible ring (shadcn shared keyboard-accessibility treatment)", () => {
    render(<AttributionPage />);
    const btn = screen.getByRole("button", { name: /run demo attribution/i });
    expect(btn.className).toContain("focus-visible:ring");
  });

  it("preserves layout spacing (mb-6) so the surrounding grid is unchanged", () => {
    render(<AttributionPage />);
    const btn = screen.getByRole("button", { name: /run demo attribution/i });
    expect(btn.className).toContain("mb-6");
  });

  it("is enabled on initial render and shows the idle label", () => {
    render(<AttributionPage />);
    const btn = screen.getByRole("button", { name: /run demo attribution/i });
    expect(btn).not.toBeDisabled();
    expect(btn).toHaveTextContent("Run Demo Attribution");
  });
});
