import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductCandidateCard } from "@/components/commerce/ProductCandidateCard";
import { ProductSearchResults } from "@/components/commerce/ProductSearchResults";

import { REQUIREMENT, candidate, match } from "./commerceFixtures";

describe("ProductCandidateCard", () => {
  it("shows observed details, price, MRP and the deterministic match explanation", () => {
    const c = candidate(1);
    render(<ProductCandidateCard candidate={c} match={match(c)} />);
    expect(screen.getByTestId("candidate-name")).toHaveTextContent("Amul Taaza Toned Fresh Milk");
    expect(screen.getByTestId("candidate-price")).toHaveTextContent("₹56.00");
    expect(screen.getByText("₹58.00")).toHaveClass("line-through");
    expect(screen.getByTestId("candidate-match")).toHaveTextContent("98% match · 2 packs — Exact match");
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("never fabricates missing ratings, prices, sellers or sizes", () => {
    render(<ProductCandidateCard candidate={candidate(2, { normalized_price: null, list_price: null, pack_size: null, availability: "UNKNOWN" })} />);
    expect(screen.getByTestId("candidate-price")).toHaveTextContent("Price not shown");
    expect(screen.getByText("No size/variant shown")).toBeInTheDocument();
    expect(screen.getByText("Availability not shown")).toBeInTheDocument();
    expect(screen.queryByText(/out of 5|sold by/i)).not.toBeInTheDocument();
  });

  it("shows ratings, delivery and seller only when the website showed them", () => {
    render(<ProductCandidateCard candidate={candidate(3, { rating: "4.1 out of 5 stars", review_count: "1,204", delivery_estimate: "FREE delivery Tue", seller: "Fixture Retail" })} />);
    expect(screen.getByText("4.1 out of 5 stars (1,204)")).toBeInTheDocument();
    expect(screen.getByText("FREE delivery Tue")).toBeInTheDocument();
    expect(screen.getByText("Sold by Fixture Retail")).toBeInTheDocument();
  });

  it("marks unavailable and disqualified products", () => {
    const c = candidate(4, { availability: "UNAVAILABLE", product_name: "Amul Gold Full Cream Milk" });
    render(<ProductCandidateCard candidate={c} match={match(c, { disqualified: true, overall_score: 0.4, exact_match: false, packs_needed: null, explanation: "taaza requested, listing is gold" })} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("product-candidate")).toHaveAttribute("data-disqualified", "true");
    expect(screen.getByTestId("candidate-match")).toHaveTextContent("40% match — taaza requested, listing is gold");
  });
});

describe("ProductSearchResults", () => {
  it("lists each requested product with its real status and message", () => {
    const c = candidate(1);
    render(
      <ProductSearchResults requirements={[
        { requirement: REQUIREMENT, status: "ADDED", decision: "SELECTED", message: "cart quantity 0 → 2", candidates: [c], matches: [match(c)], selected_candidate_id: c.candidate_id, packs_added: 2 },
        { requirement: { ...REQUIREMENT, product_id: "00000000-0000-4000-8000-0000000003ff", query: "Amul paneer", quantity: 200, unit: "GRAM" }, status: "UNAVAILABLE", decision: "UNAVAILABLE", message: "Amul paneer — 200 g is shown but currently unavailable.", candidates: [], matches: [], selected_candidate_id: null, packs_added: 0 },
      ]} />,
    );
    const rows = screen.getAllByTestId("requirement");
    expect(rows.map((r) => r.getAttribute("data-status"))).toEqual(["ADDED", "UNAVAILABLE"]);
    expect(rows[0]).toHaveTextContent("Amul taaza milk · 2 liter");
    expect(rows[1]).toHaveTextContent("currently unavailable");
  });
});
