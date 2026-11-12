import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CartSummary } from "@/components/commerce/CartSummary";
import { PriceBreakdown } from "@/components/commerce/PriceBreakdown";
import { ShoppingPanel } from "@/components/commerce/ShoppingPanel";
import { formatInr } from "@/lib/commerceApi";

import { CART, summary, verification } from "./commerceFixtures";

describe("PriceBreakdown", () => {
  it("never shows unobserved fees as ₹0", () => {
    render(<PriceBreakdown subtotal="208.00" deliveryFee={null} handlingFee="4.00" discount={null} tax={null} total={null} />);
    const box = screen.getByTestId("price-breakdown");
    expect(within(box).getByText("₹208.00")).toBeInTheDocument();
    expect(box.querySelector('[data-field="delivery"]')).toHaveTextContent("Not available");
    expect(box.querySelector('[data-field="total"]')).toHaveTextContent("Not available");
    expect(box).not.toHaveTextContent("₹0.00");
  });

  it("formats INR with Indian grouping and shows discounts as negative", () => {
    expect(formatInr("123456.5")).toBe("₹1,23,456.50");
    expect(formatInr("-20.00")).toBe("-₹20.00");
    expect(formatInr(null)).toBe("Not available");
  });
});

describe("CartSummary", () => {
  it("renders the observed cart, quantities, totals and verified status", () => {
    render(<CartSummary cart={CART} verification={verification()} siteName="Blinkit" />);
    expect(screen.getAllByTestId("cart-item")).toHaveLength(2);
    expect(screen.getAllByTestId("cart-item-qty").map((q) => q.textContent)).toEqual(["2", "1"]);
    expect(screen.getByTestId("cart-verification")).toHaveTextContent("Cart verified");
    expect(screen.getByText(/no order has been placed/i)).toBeInTheDocument();
    expect(screen.getByTestId("price-breakdown").querySelector('[data-field="total"]')).toHaveTextContent("₹212.00");
  });

  it("shows missing items and mismatches instead of success", () => {
    render(
      <CartSummary cart={CART} siteName="Blinkit"
        verification={verification({ status: "PARTIAL", missing_items: ["Amul paneer — 200 g"], mismatched_items: ["Amul milk — 2 L (quantity mismatch)"] })} />,
    );
    expect(screen.getByTestId("cart-verification")).toHaveTextContent("Partly prepared");
    expect(screen.getByTestId("missing-items")).toHaveTextContent("Amul paneer — 200 g");
    expect(screen.getByTestId("mismatched-items")).toHaveTextContent("quantity mismatch");
    expect(screen.queryByText(/every requested item/i)).not.toBeInTheDocument();
  });

  it("quantity controls call back with the exact item and value", async () => {
    const onChange = vi.fn();
    render(<CartSummary cart={CART} verification={verification()} siteName="Blinkit" onChangeQuantity={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Increase Farm Fresh White Eggs" }));
    expect(onChange).toHaveBeenCalledWith(CART.items[1]!.item_id, 2);
  });
});

describe("ShoppingPanel", () => {
  it("labels fixtures and says no order was placed", () => {
    render(<ShoppingPanel summary={summary()} onChooseProduct={vi.fn()} />);
    expect(screen.getByText("Test fixture")).toBeInTheDocument();
    expect(screen.getByTestId("shopping-status")).toHaveTextContent("Cart verified");
    expect(screen.getByTestId("no-order-note")).toBeInTheDocument();
  });
});
