# Product matching (deterministic)

`backend/app/commerce/matching/`. The LLM never sets a score.

```
overall = 0.25·brand + 0.35·name + 0.25·quantity + 0.15·variant
```
- **brand:** 1 if the requested brand's words appear in the listing, else 0. When a brand was named, `must_match_brand=true`, so a wrong brand is **disqualified**.
- **name:** coverage of the product words (plus model and category). Category aliases cover titles that don't name the category, e.g. a "Galaxy M34 5G" is a phone and a "Vivobook" is a laptop.
- **quantity:** parses the pack size (`1 ltr`, `500 ml`, `2 x 500 ml`, `Pack of 6`, `12 pieces`, `1 kg`) and converts units (1 L = 1000 ml, 1 kg = 1000 g, 1 dozen = 12 pcs). One exact pack scores 1.0. Identical packs that sum to exactly the requested amount score 0.9, minus a little per extra pack, up to `COMMERCE_MAX_PACKS_PER_ITEM`. A size that can't make the amount exactly is **disqualified**. An unreadable size scores 0.5 and needs confirmation.
- **variant:** product lines (Taaza / Gold / Slim…, white / brown / multigrain…) and specs (RAM, storage, colour). A conflicting line or spec is **disqualified**; an unverifiable one scores 0.5.
- **budget / availability:** a price above `max_price` or an unavailable listing is **disqualified**.

Disqualified candidates are capped at 0.40.

## Decisions (thresholds in settings)
| Condition | Decision |
| --- | --- |
| no viable candidate ≥ `COMMERCE_ACCEPTABLE_MATCH_THRESHOLD` (0.80) | `NOT_FOUND`, or `UNAVAILABLE` when the matching product is out of stock |
| ≥ 2 *different* products within `COMMERCE_AMBIGUITY_MARGIN` (0.05) | `AMBIGUOUS`: the user chooses (dialog) |
| exact match ≥ `COMMERCE_EXACT_MATCH_THRESHOLD` (0.92) | `SELECTED` |
| otherwise | `NEEDS_CONFIRMATION`: the user chooses |

The same product in another pack size is **not** ambiguous; the fewest packs win (1 × 1 L beats 2 × 500 ml). Examples, all covered by tests:
- "2 L Amul Taaza": Taaza 1 L × 2 is selected; Gold is wrong variant; Mother Dairy is wrong brand; Taaza 500 ml would need 4 packs.
- "2 L Amul milk" (no line given): Taaza vs Gold is ambiguous, so the user is asked.
- "16 GB / 512 GB laptop under ₹60,000": the 8 GB model and the over-budget model are excluded; two remaining equal options go to the user.

The user's choice (`POST /tasks/{id}/commerce/selection`) is bound to the task, the requirement and the offered candidate IDs. Skipping is allowed; the item is then reported as not added.
