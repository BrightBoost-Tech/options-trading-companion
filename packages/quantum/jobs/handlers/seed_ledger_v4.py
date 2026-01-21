"""
Seed Ledger v4 Job Handler

Bootstraps the canonical position ledger from broker snapshot (positions table).
Creates opening balance entries for positions that exist in broker but not in ledger.

Usage:
    Enqueue: {"job_name": "seed_ledger_v4"}
    Payload:
        - user_id: str (optional, runs for all users with positions if omitted)
        - dry_run: bool (optional, if True shows what would be created without writing)
        - force: bool (optional, if True re-seeds even if symbol exists in ledger)
"""

import hashlib
import logging
import traceback
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set

from packages.quantum.nested_logging import _get_supabase_client

JOB_NAME = "seed_ledger_v4"

logger = logging.getLogger(__name__)

# Position type values that indicate SHORT position
SHORT_POSITION_TYPES = {
    "short", "SHORT", "sell", "SELL", "short_position", "SHORT_POSITION",
    "sold", "SOLD", "written", "WRITTEN",
}

# Position type values that indicate LONG position
LONG_POSITION_TYPES = {
    "long", "LONG", "buy", "BUY", "long_position", "LONG_POSITION",
    "bought", "BOUGHT", "held", "HELD",
}


def run(payload: Dict[str, Any], ctx=None) -> Dict[str, Any]:
    """
    Job handler for seeding v4 position ledger from broker snapshot.

    Reads existing positions from broker snapshot cache (positions table)
    and creates opening balance entries in the ledger for positions
    that don't already exist.

    Payload:
        user_id: Optional single user to seed
        dry_run: If True, show what would be created without writing (default False)
        force: If True, re-seed even if symbol exists (default False)

    Returns:
        Dict with seeding summary
    """
    logger.info(f"[SEED_LEDGER_V4] Starting with payload: {payload}")

    try:
        supabase = _get_supabase_client()
        if not supabase:
            return {"status": "failed", "error": "Database unavailable"}

        dry_run = payload.get("dry_run", False)
        force = payload.get("force", False)
        user_id = payload.get("user_id")

        # Single user mode
        if user_id:
            result = _seed_user(supabase, user_id, dry_run, force)
            return {
                "status": "completed",
                "users_processed": 1,
                "results": {user_id: result},
            }

        # Batch mode: fetch all users with broker positions
        users = _get_users_with_broker_positions(supabase)

        if not users:
            logger.info("[SEED_LEDGER_V4] No users with broker positions found")
            return {
                "status": "completed",
                "users_processed": 0,
                "results": {},
            }

        logger.info(f"[SEED_LEDGER_V4] Processing {len(users)} users")

        results = {}
        total_seeded = 0
        total_skipped = 0
        errors = 0

        for uid in users:
            try:
                result = _seed_user(supabase, uid, dry_run, force)
                results[uid] = result
                total_seeded += result.get("seeded", 0)
                total_skipped += result.get("skipped", 0)
            except Exception as ex:
                logger.error(f"[SEED_LEDGER_V4] Error for user {uid}: {ex}")
                results[uid] = {"status": "error", "error": str(ex)}
                errors += 1

        return {
            "status": "completed",
            "users_processed": len(users),
            "total_seeded": total_seeded,
            "total_skipped": total_skipped,
            "errors": errors,
            "dry_run": dry_run,
            "results": results,
        }

    except Exception as e:
        logger.error(f"[SEED_LEDGER_V4] Job failed: {e}")
        logger.error(traceback.format_exc())
        return {"status": "failed", "error": str(e)}


def _seed_user(
    supabase,
    user_id: str,
    dry_run: bool,
    force: bool,
) -> Dict[str, Any]:
    """
    Seed ledger for a single user from broker snapshot.

    Process:
    1. Load broker positions (qty != 0)
    2. Load existing OPEN ledger symbols
    3. For each broker position not in ledger:
       - Create position_group with strategy_key="SEED_V4"
       - Create position_leg
       - Create position_event (CASH_ADJ with opening_balance meta)
    """
    logger.info(f"[SEED_LEDGER_V4] Seeding user: {user_id}")

    # Fetch broker positions
    broker_positions = _get_broker_positions(supabase, user_id)

    if not broker_positions:
        logger.info(f"[SEED_LEDGER_V4] No broker positions for user {user_id}")
        return {
            "status": "no_positions",
            "broker_positions": 0,
            "seeded": 0,
            "skipped": 0,
        }

    # Fetch existing ledger symbols (OPEN groups only)
    existing_symbols = _get_ledger_symbols(supabase, user_id) if not force else set()

    seeded = []
    skipped = []

    for pos in broker_positions:
        symbol = pos.get("symbol")
        if not symbol:
            continue

        qty = int(pos.get("qty") or pos.get("quantity") or 0)
        if qty == 0:
            continue

        # Skip if already in ledger (unless force mode)
        if symbol in existing_symbols:
            skipped.append({
                "symbol": symbol,
                "reason": "already_in_ledger",
            })
            continue

        avg_price = pos.get("avg_price")

        # Infer side using v2 logic (position_type takes precedence)
        side, side_meta = _infer_side_from_snapshot_row(pos)

        if dry_run:
            seeded.append({
                "symbol": symbol,
                "qty": qty,
                "avg_price": avg_price,
                "side": side,
                "side_inference": side_meta,
                "dry_run": True,
            })
            continue

        # Create seed entries
        try:
            result = _create_seed_entries(
                supabase=supabase,
                user_id=user_id,
                symbol=symbol,
                qty=qty,
                avg_price=avg_price,
                side=side,
                side_meta=side_meta,
            )
            seeded.append({
                "symbol": symbol,
                "qty": qty,
                "avg_price": avg_price,
                "group_id": result.get("group_id"),
                "leg_id": result.get("leg_id"),
                "event_id": result.get("event_id"),
            })
            # Add to existing symbols to prevent duplicates within same run
            existing_symbols.add(symbol)
        except Exception as ex:
            logger.error(f"[SEED_LEDGER_V4] Failed to seed {symbol}: {ex}")
            skipped.append({
                "symbol": symbol,
                "reason": f"error: {str(ex)[:50]}",
            })

    return {
        "status": "dry_run" if dry_run else "seeded",
        "broker_positions": len(broker_positions),
        "seeded": len(seeded),
        "skipped": len(skipped),
        "seeded_positions": seeded[:20],  # Cap for payload size
        "skipped_positions": skipped[:20],
    }


def _create_seed_entries(
    supabase,
    user_id: str,
    symbol: str,
    qty: int,
    avg_price: Optional[float],
    side: Optional[str] = None,
    side_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create position_group, position_leg, and position_event for a seed entry.

    Args:
        supabase: Supabase client
        user_id: User UUID
        symbol: Position symbol
        qty: Position quantity (signed)
        avg_price: Average cost basis
        side: Pre-computed side ("LONG" or "SHORT"), uses v2 inference if provided
        side_meta: Metadata about how side was inferred

    Returns dict with group_id, leg_id, event_id.
    """
    # Use provided side or fall back to qty sign (v1 behavior)
    if side is None:
        side = "LONG" if qty > 0 else "SHORT"
        side_meta = {"side_inferred": "qty_sign", "version": "v1"}

    abs_qty = abs(qty)

    # Extract underlying from symbol
    underlying = _extract_underlying(symbol)

    # Build deterministic identifiers (v2 style)
    legs_fingerprint = _build_seed_fingerprint_v2(symbol, side, abs_qty, avg_price)
    event_key = _build_seed_event_key_v2(user_id, symbol, qty, avg_price, side)

    # Check for existing event (idempotency)
    existing_event = _check_event_exists(supabase, user_id, event_key)
    if existing_event:
        logger.info(f"[SEED_LEDGER_V4] Seed already exists for {symbol}, event_key={event_key}")
        return {
            "group_id": existing_event.get("group_id"),
            "leg_id": existing_event.get("leg_id"),
            "event_id": existing_event.get("id"),
            "deduplicated": True,
        }

    # Determine right (option type) from symbol
    right = _infer_right_from_symbol(symbol)

    # Step 1: Create position_group
    group_data = {
        "user_id": user_id,
        "underlying": underlying,
        "legs_fingerprint": legs_fingerprint,
        "strategy_key": "SEED_V4",
        "strategy": "seed_opening_balance",
        "status": "OPEN",
        "fees_paid": 0,
    }

    group_result = supabase.table("position_groups").insert(group_data).execute()
    if not group_result.data:
        raise Exception("Failed to create position_group")

    group = group_result.data[0]
    group_id = group["id"]

    logger.info(f"[SEED_LEDGER_V4] Created group: {group_id} for {symbol}")

    # Step 2: Create position_leg
    leg_data = {
        "group_id": group_id,
        "user_id": user_id,
        "symbol": symbol,
        "underlying": underlying,
        "right": right,
        "side": side,
        "qty_opened": abs_qty,
        "qty_closed": 0,
        "avg_cost_open": float(avg_price) if avg_price else None,
        "multiplier": 100 if right in ("C", "P") else 1,
    }

    leg_result = supabase.table("position_legs").insert(leg_data).execute()
    if not leg_result.data:
        raise Exception("Failed to create position_leg")

    leg = leg_result.data[0]
    leg_id = leg["id"]

    logger.info(f"[SEED_LEDGER_V4] Created leg: {leg_id} for {symbol}")

    # Step 3: Compute cash impact (if avg_price known)
    cash_impact = None
    meta_json = {
        "opening_balance": True,
        "source": "broker_snapshot",
        "seed_version": "v2",
    }

    # Include side inference metadata
    if side_meta:
        meta_json["side_inference"] = side_meta
        if side_meta.get("needs_review"):
            meta_json["needs_review"] = True

    if avg_price is not None:
        multiplier = 100 if right in ("C", "P") else 1
        notional = Decimal(str(avg_price)) * abs_qty * multiplier

        if side == "LONG":
            # Bought position: cash outflow (negative)
            cash_impact = float(-notional)
        else:
            # Short position: cash inflow (positive)
            cash_impact = float(notional)
    else:
        meta_json["cost_unknown"] = True
        meta_json["note"] = "avg_price not available from broker snapshot"

    # Step 4: Create position_event (CASH_ADJ with opening_balance meta)
    event_data = {
        "user_id": user_id,
        "group_id": group_id,
        "leg_id": leg_id,
        "event_type": "CASH_ADJ",
        "amount_cash": cash_impact,
        "qty_delta": qty,  # Signed qty
        "event_key": event_key,
        "meta_json": meta_json,
    }

    event_result = supabase.table("position_events").insert(event_data).execute()
    if not event_result.data:
        raise Exception("Failed to create position_event")

    event = event_result.data[0]
    event_id = event["id"]

    logger.info(f"[SEED_LEDGER_V4] Created event: {event_id} for {symbol}")

    return {
        "group_id": group_id,
        "leg_id": leg_id,
        "event_id": event_id,
    }


def _get_users_with_broker_positions(supabase) -> List[str]:
    """Get list of users with non-zero broker positions."""
    try:
        res = supabase.table("positions") \
            .select("user_id") \
            .neq("qty", 0) \
            .execute()

        users = set(r["user_id"] for r in (res.data or []) if r.get("user_id"))
        return list(users)
    except Exception as e:
        logger.error(f"[SEED_LEDGER_V4] Error fetching users: {e}")
        return []


def _get_broker_positions(supabase, user_id: str) -> List[Dict[str, Any]]:
    """Fetch broker positions from positions table for a user."""
    try:
        res = supabase.table("positions") \
            .select("symbol, qty, quantity, avg_price, underlying, position_type") \
            .eq("user_id", user_id) \
            .neq("qty", 0) \
            .execute()
        return res.data or []
    except Exception as e:
        logger.error(f"[SEED_LEDGER_V4] Error fetching positions for {user_id}: {e}")
        return []


def _get_ledger_symbols(supabase, user_id: str) -> Set[str]:
    """Get set of symbols already in OPEN ledger positions."""
    try:
        # Get OPEN groups for user
        groups_res = supabase.table("position_groups") \
            .select("id") \
            .eq("user_id", user_id) \
            .eq("status", "OPEN") \
            .execute()

        if not groups_res.data:
            return set()

        group_ids = [g["id"] for g in groups_res.data]

        # Get symbols from legs in those groups
        legs_res = supabase.table("position_legs") \
            .select("symbol") \
            .in_("group_id", group_ids) \
            .execute()

        return set(leg["symbol"] for leg in (legs_res.data or []) if leg.get("symbol"))

    except Exception as e:
        logger.error(f"[SEED_LEDGER_V4] Error fetching ledger symbols: {e}")
        return set()


def _check_event_exists(supabase, user_id: str, event_key: str) -> Optional[Dict[str, Any]]:
    """Check if event with event_key already exists (idempotency)."""
    try:
        result = supabase.table("position_events") \
            .select("id, group_id, leg_id") \
            .eq("user_id", user_id) \
            .eq("event_key", event_key) \
            .limit(1) \
            .execute()

        if result.data and len(result.data) > 0:
            return result.data[0]
        return None
    except Exception as e:
        logger.warning(f"[SEED_LEDGER_V4] Error checking event existence: {e}")
        return None


def _build_seed_fingerprint(symbol: str, side: str) -> str:
    """
    Build deterministic fingerprint for seed group (v1).

    DEPRECATED: Use _build_seed_fingerprint_v2 for new code.
    """
    fingerprint_str = f"SEED:{symbol}:{side}"
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def _build_seed_fingerprint_v2(
    symbol: str,
    side: str,
    qty: int,
    avg_price: Optional[float],
) -> str:
    """
    Build deterministic fingerprint for seed group (v2).

    V2 includes qty and avg_price for better uniqueness.
    Format: "SEEDv2:{symbol}:{side}:{qty}:{avg_price|null}"
    """
    price_str = f"{avg_price:.4f}" if avg_price else "null"
    fingerprint_str = f"SEEDv2:{symbol}:{side}:{qty}:{price_str}"
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


def _build_seed_event_key(
    user_id: str,
    symbol: str,
    qty: int,
    avg_price: Optional[float],
) -> str:
    """
    Build deterministic event key for seed event (v1).

    DEPRECATED: Use _build_seed_event_key_v2 for new code.
    """
    price_str = f"{avg_price:.4f}" if avg_price else "null"
    return f"seed:{user_id}:{symbol}:{qty}:{price_str}"


def _build_seed_event_key_v2(
    user_id: str,
    symbol: str,
    qty: int,
    avg_price: Optional[float],
    side: str,
) -> str:
    """
    Build deterministic event key for seed event (v2).

    V2 includes side for cases where same symbol/qty could have different sides.
    """
    price_str = f"{avg_price:.4f}" if avg_price else "null"
    return f"seedv2:{user_id}:{symbol}:{side}:{qty}:{price_str}"


def _infer_side_from_snapshot_row(row: Dict[str, Any]) -> tuple:
    """
    Infer position side (LONG/SHORT) from broker snapshot row.

    Priority:
    1. position_type field (most explicit)
    2. side/direction fields
    3. qty sign (fallback)
    4. Default to LONG with uncertainty flag

    Args:
        row: Broker position row dict

    Returns:
        Tuple of (side: str, meta: dict) where meta contains inference details
    """
    # Priority 1: Check position_type field
    position_type = row.get("position_type", "")
    if position_type:
        position_type_str = str(position_type).strip()
        if position_type_str in SHORT_POSITION_TYPES:
            return "SHORT", {"side_inferred": "position_type", "value": position_type_str, "version": "v2"}
        if position_type_str in LONG_POSITION_TYPES:
            return "LONG", {"side_inferred": "position_type", "value": position_type_str, "version": "v2"}

    # Priority 2: Check side/direction fields
    for field in ["side", "direction", "position_side"]:
        field_value = row.get(field, "")
        if field_value:
            field_value_str = str(field_value).strip().lower()
            if field_value_str in ["short", "sell", "sold", "written"]:
                return "SHORT", {"side_inferred": field, "value": field_value_str, "version": "v2"}
            if field_value_str in ["long", "buy", "bought", "held"]:
                return "LONG", {"side_inferred": field, "value": field_value_str, "version": "v2"}

    # Priority 3: Use qty sign
    qty = row.get("qty") or row.get("quantity") or 0
    try:
        qty_int = int(qty)
        if qty_int < 0:
            return "SHORT", {"side_inferred": "qty_sign", "qty": qty_int, "version": "v2"}
        if qty_int > 0:
            return "LONG", {"side_inferred": "qty_sign", "qty": qty_int, "version": "v2"}
    except (ValueError, TypeError):
        pass

    # Priority 4: Default to LONG with uncertainty
    return "LONG", {
        "side_inferred": "default_long",
        "needs_review": True,
        "note": "Could not determine side from broker data",
        "version": "v2",
    }


def _extract_underlying(symbol: str) -> str:
    """Extract underlying from option symbol or return as-is for stock."""
    if not symbol:
        return "UNKNOWN"

    # Options symbols are typically like "AAPL240119C00150000"
    if len(symbol) > 10 and any(c.isdigit() for c in symbol):
        underlying = ""
        for c in symbol:
            if c.isalpha():
                underlying += c
            else:
                break
        return underlying or symbol

    return symbol


def _infer_right_from_symbol(symbol: str) -> str:
    """Infer option right (C/P) from symbol, or S for stock."""
    if not symbol:
        return "S"

    # Check if it's an option symbol (long with digits)
    if len(symbol) > 10 and any(c.isdigit() for c in symbol):
        # Standard OCC format: AAPL240119C00150000
        # Look for C or P after the date portion
        for i, c in enumerate(symbol):
            if c.isdigit():
                # Found start of date, look for C or P
                remaining = symbol[i:]
                for ch in remaining:
                    if ch == "C":
                        return "C"
                    elif ch == "P":
                        return "P"
                break

    return "S"  # Default to stock
