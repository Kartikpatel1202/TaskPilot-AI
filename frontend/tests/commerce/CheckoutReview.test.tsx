import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CheckoutReview } from "@/components/commerce/CheckoutReview";
import { OrderStatus } from "@/components/commerce/OrderStatus";
import { PaymentHandoff } from "@/components/commerce/PaymentHandoff";
import { ShoppingPanel } from "@/components/commerce/ShoppingPanel";

import { TASK } from "../fixtures";
import { CHECKOUT, summary } from "./commerceFixtures";

describe("CheckoutReview", () => {
  it("shows items, final total, masked address, slot and payment — and that nothing was purchased", () => {
    render(<CheckoutReview checkout={CHECKOUT} />);
    const box = screen.getByTestId("checkout-review");
    expect(box).toHaveTextContent("Amul Taaza Toned Fresh Milk");
    expect(box.querySelector('[data-field="total"]')).toHaveTextContent("₹212.00");
    expect(box).toHaveTextContent("Home: •••, Gurugram 122•••");
    expect(box).toHaveTextContent("Delivery in 12 minutes");
    expect(screen.getByTestId("checkout-payment")).toHaveTextContent("Cash on Delivery");
    expect(screen.getByTestId("checkout-verified")).toHaveTextContent("Verified");
    expect(box).toHaveTextContent(/nothing has been purchased/i);
  });

  it("shows price-change warnings and an unverified checkout", () => {
    render(<CheckoutReview checkout={{ ...CHECKOUT, is_verified: false, warnings: ["The final total could not be read."] }}
      priceChanges={["Order total: price increased from ₹500.00 to ₹540.00 (+₹40.00, 8.00%) — significant change."]} />);
    expect(screen.getByTestId("checkout-verified")).toHaveTextContent("Not verified");
    const warnings = screen.getAllByTestId("checkout-warning").map((w) => w.textContent);
    expect(warnings.some((w) => w?.includes("+₹40.00"))).toBe(true);
    expect(warnings.some((w) => w?.includes("could not be read"))).toBe(true);
  });
});

describe("PaymentHandoff and OrderStatus", () => {
  it("hands prepaid payment to the user with no payment fields", () => {
    render(<PaymentHandoff siteName="Amazon India" checkout={CHECKOUT}
      order={{ task_id: TASK, status: "PAYMENT_HANDOFF", message: "Please choose a payment method and pay yourself." }} />);
    const box = screen.getByTestId("payment-handoff");
    expect(box).toHaveTextContent(/complete the payment manually on the merchant website/i);
    expect(box).toHaveTextContent("₹212.00");
    expect(box.querySelector("input")).toBeNull();
  });

  it("confirms an order only with the website's own confirmation", () => {
    const { rerender } = render(<OrderStatus order={{ task_id: TASK, status: "CONFIRMED", message: "The website shows the order as placed.", order_reference: "FXB-100001" }} />);
    expect(screen.getByTestId("order-status")).toHaveTextContent("Order confirmed");
    expect(screen.getByTestId("order-status")).toHaveTextContent("FXB-100001");
    rerender(<OrderStatus order={{ task_id: TASK, status: "UNKNOWN", message: "No order confirmation was visible." }} />);
    expect(screen.getByTestId("order-status")).toHaveTextContent("Order status could not be verified");
    expect(screen.getByRole("alert")).toHaveTextContent(/will not submit again/i);
  });

  it("the shopping panel shows the handoff state", () => {
    render(<ShoppingPanel onChooseProduct={vi.fn()} summary={summary({ status: "PAYMENT_HANDOFF", checkout: CHECKOUT,
      order: { task_id: TASK, status: "PAYMENT_HANDOFF", message: "Pay yourself." } })} />);
    expect(screen.getByTestId("payment-handoff")).toBeInTheDocument();
    expect(screen.getByTestId("order-status")).toHaveAttribute("data-status", "PAYMENT_HANDOFF");
  });
});
