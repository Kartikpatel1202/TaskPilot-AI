import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ProductSelectionDialog } from "@/components/commerce/ProductSelectionDialog";

import { TASK, uuidFor } from "../fixtures";
import { NOW, REQUIREMENT, candidate, match } from "./commerceFixtures";

import type { RequirementProgress } from "@/types/commerce";

const harvest = candidate(10, { product_name: "Harvest Gold White Bread", pack_size: "400 g", normalized_price: "40.00", list_price: null });
const britannia = candidate(11, { product_name: "Britannia 100% Whole Wheat Bread", pack_size: "400 g", normalized_price: "55.00", list_price: null });
const entry: RequirementProgress = {
  requirement: { ...REQUIREMENT, query: "bread", product_name: "bread", brand: null, quantity: 1, unit: "PACK", preferred_variant: {}, must_match_brand: false },
  status: "AWAITING_SELECTION", decision: "AMBIGUOUS", message: null, candidates: [harvest, britannia],
  matches: [match(harvest, { overall_score: 0.975 }), match(britannia, { overall_score: 0.975 })], selected_candidate_id: null, packs_added: 0,
};
const selection = { selection_id: uuidFor(700), task_id: TASK, requirement_id: REQUIREMENT.product_id, question: "2 products match bread — 1 pack equally well — please choose one.", candidate_ids: [harvest.candidate_id, britannia.candidate_id], expires_at: NOW };

function setup(onChoose = vi.fn().mockResolvedValue({ ok: true })) {
  render(<ProductSelectionDialog open selection={selection} requirement={entry} onChoose={onChoose} onOpenChange={vi.fn()} />);
  return onChoose;
}

describe("ProductSelectionDialog", () => {
  it("shows every equally matching real product and the question", () => {
    setup();
    expect(screen.getByText(/please choose one/i)).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByRole("radio", { name: "Harvest Gold White Bread, 400 g, ₹40.00" })).toBeInTheDocument();
    expect(screen.getByText("Harvest Gold White Bread")).toBeInTheDocument();
    expect(screen.getByText("Britannia 100% Whole Wheat Bread")).toBeInTheDocument();
  });

  it("never auto-selects: confirm is disabled until the user picks", async () => {
    const onChoose = setup();
    expect(screen.getByTestId("confirm-selection")).toBeDisabled();
    await userEvent.click(screen.getByText("Britannia 100% Whole Wheat Bread"));
    expect(screen.getAllByRole("radio")[1]).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByTestId("confirm-selection"));
    expect(onChoose).toHaveBeenCalledWith(selection.selection_id, britannia.candidate_id);
  });

  it("lets the user skip the product", async () => {
    const onChoose = setup();
    await userEvent.click(screen.getByRole("button", { name: /skip this product/i }));
    expect(onChoose).toHaveBeenCalledWith(selection.selection_id, null);
  });

  it("shows backend errors", async () => {
    setup(vi.fn().mockResolvedValue({ ok: false, error: "This product choice is no longer pending." }));
    await userEvent.click(screen.getByText("Harvest Gold White Bread"));
    await userEvent.click(screen.getByTestId("confirm-selection"));
    expect(await screen.findByRole("alert")).toHaveTextContent("no longer pending");
  });
});
