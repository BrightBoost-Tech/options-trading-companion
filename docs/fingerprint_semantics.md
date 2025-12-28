# Legs Fingerprint Semantics

This document defines the semantics for the `legs_fingerprint` field used in `trade_suggestions`.

## Definition (Option A: Structure-Only)

The `legs_fingerprint` is a deterministic hash of the **structural composition** of a trade's legs.

### Included Fields
- **Underlying Symbol** (e.g., `SPY`)
- **Expiry Date** (e.g., `2023-12-15`)
- **Option Type** (`C` or `P`)
- **Strike Price** (e.g., `450.0`)
- **Side** (`buy` or `sell`)

### Excluded Fields
- **Quantity** (Size)
- **Limit Price** or **Market Price**
- **Strategy Name** (though usually correlated with structure)

### Normalization rules
- Leg order is **irrelevant**. Legs are sorted before hashing.
- Symbols are parsed into canonical parts to handle formatting differences (e.g., `O:SPY...` vs `SPY...`).

## Purpose & Behavior

The purpose of this fingerprint is to uniquely identify a trade **concept** or **structure** within a given cycle window.

- **Uniqueness**: The database enforces uniqueness on `(user_id, window, cycle_date, ticker, strategy, legs_fingerprint)`.
- **Collisions**: Two suggestions with the same structure but different sizes (e.g., "Buy 1 Contract" vs "Buy 5 Contracts") will generate the **SAME** fingerprint.
- **Updates**: If the system generates a new suggestion with the same structure (fingerprint) but updated sizing or pricing, it is treated as an **update** to the existing suggestion, not a new one. The workflow logic should `UPSERT` such records, effectively overwriting the old size/price with the new one.

This prevents the UI from being cluttered with duplicate cards for the exact same option spread just because the suggested limit price shifted by a few cents or the position sizer adjusted the quantity.
