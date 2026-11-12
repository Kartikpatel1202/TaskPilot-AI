import { CheckCircle2, CircleSlash, Star, Truck } from "lucide-react";
import { memo } from "react";

import { formatInr } from "@/lib/commerceApi";
import { cn } from "@/lib/utils";

import type { ProductCandidate, ProductMatch } from "@/types/product";

interface ProductCandidateCardProps {
  candidate: ProductCandidate;
  match?: ProductMatch | null;
  selected?: boolean;
  /** Renders the card as a selectable option (used by ProductSelectionDialog). */
  selectable?: boolean;
  onSelect?: (candidateId: string) => void;
}

/** One product exactly as read from the website. Missing details are shown as missing, never invented. */
export const ProductCandidateCard = memo(function ProductCandidateCard({ candidate, match, selected = false, selectable = false, onSelect }: ProductCandidateCardProps) {
  const unavailable = candidate.availability === "UNAVAILABLE";
  const disqualified = match?.disqualified ?? false;
  const variant = Object.entries(candidate.variant).map(([k, v]) => `${k} ${v}`).join(" · ");
  const body = (
    <>
      <div className="flex gap-3">
        {candidate.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- remote product image observed on the website
          <img src={candidate.image_url} alt="" className="h-12 w-12 shrink-0 rounded object-cover" referrerPolicy="no-referrer" />
        ) : (
          <div className="h-12 w-12 shrink-0 rounded bg-white/[0.04]" aria-hidden />
        )}
        <div className="min-w-0 flex-1">
          <p className="line-clamp-2 text-sm text-foreground" data-testid="candidate-name">{candidate.product_name}</p>
          <p className="text-[11px] text-muted-foreground">
            {[candidate.brand, candidate.pack_size, variant].filter(Boolean).join(" · ") || "No size/variant shown"}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="font-mono text-sm tabular-nums" data-testid="candidate-price">
            {candidate.normalized_price ? formatInr(candidate.normalized_price) : "Price not shown"}
          </p>
          {candidate.list_price && <p className="font-mono text-[11px] text-muted-foreground line-through">{formatInr(candidate.list_price)}</p>}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className={cn("inline-flex items-center gap-1", unavailable ? "text-level-error" : "text-level-success/90")}>
          {unavailable ? <CircleSlash className="h-3 w-3" aria-hidden /> : <CheckCircle2 className="h-3 w-3" aria-hidden />}
          {unavailable ? "Unavailable" : candidate.availability === "AVAILABLE" ? "Available" : "Availability not shown"}
        </span>
        {candidate.rating && (
          <span className="inline-flex items-center gap-1"><Star className="h-3 w-3" aria-hidden />{candidate.rating}{candidate.review_count ? ` (${candidate.review_count})` : ""}</span>
        )}
        {candidate.delivery_estimate && <span className="inline-flex items-center gap-1"><Truck className="h-3 w-3" aria-hidden />{candidate.delivery_estimate}</span>}
        {candidate.seller && <span>Sold by {candidate.seller}</span>}
        {candidate.in_cart_quantity ? <span>In cart: {candidate.in_cart_quantity}</span> : null}
      </div>
      {match && (
        <p className={cn("text-[11px]", disqualified ? "text-level-error/90" : match.exact_match ? "text-level-success" : "text-level-warning")} data-testid="candidate-match">
          {Math.round(match.overall_score * 100)}% match{match.packs_needed && match.packs_needed > 1 ? ` · ${match.packs_needed} packs` : ""} — {match.explanation}
        </p>
      )}
    </>
  );
  const classes = cn(
    "flex w-full flex-col gap-2 rounded-lg border p-3 text-left",
    selected ? "border-cyan-brand/60 bg-cyan-brand/[0.06]" : "border-white/[0.06] bg-white/[0.02]",
    (unavailable || disqualified) && "opacity-60",
  );
  if (selectable) {
    return (
      <button type="button" role="radio" aria-checked={selected} className={classes} disabled={unavailable}
        aria-label={`${candidate.product_name}${candidate.pack_size ? `, ${candidate.pack_size}` : ""}${candidate.normalized_price ? `, ₹${candidate.normalized_price}` : ""}`}
        onClick={() => onSelect?.(candidate.candidate_id)} data-testid="product-candidate">
        {body}
      </button>
    );
  }
  return <article className={classes} data-testid="product-candidate" data-disqualified={disqualified || undefined}>{body}</article>;
});
