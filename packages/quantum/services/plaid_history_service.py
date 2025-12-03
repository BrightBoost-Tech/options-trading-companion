from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
from supabase import Client
import json

class PlaidHistoryService:
    def __init__(self, plaid_client, supabase: Client):
        self.plaid = plaid_client
        self.supabase = supabase

    async def backfill_snapshots(
        self,
        user_id: str,
        start_date: str,
        end_date: str
    ) -> int:
        """
        Backfills historical portfolio snapshots using Plaid Investment Transactions.
        """
        print(f"Backfilling snapshots for {user_id} from {start_date} to {end_date}")

        # 1. Get Access Token
        access_token = self._get_access_token(user_id)
        if not access_token:
            print(f"No access token found for user {user_id}")
            return 0

        # 2. Fetch Investment Transactions
        try:
            # We need to call Plaid API.
            # Assuming self.plaid is the plaid_api client wrapper or raw client.
            # Usually strict typing requires constructing request objects.
            # Using the plaid_service.py style.

            # Since I don't have the plaid models imported here, I'll rely on the
            # calling code or plaid_service to have set up the client correctly.
            # But wait, I need to make the calls.

            from plaid.model.investments_transactions_get_request import InvestmentsTransactionsGetRequest
            from plaid.model.investments_transactions_get_request_options import InvestmentsTransactionsGetRequestOptions

            # Pagination loop
            all_transactions = []
            offset = 0

            while True:
                request = InvestmentsTransactionsGetRequest(
                    access_token=access_token,
                    start_date=datetime.strptime(start_date, "%Y-%m-%d").date(),
                    end_date=datetime.strptime(end_date, "%Y-%m-%d").date(),
                    options=InvestmentsTransactionsGetRequestOptions(
                        offset=offset
                    )
                )

                response = self.plaid.investments_transactions_get(request)
                transactions = response['investment_transactions']
                all_transactions.extend(transactions)

                if len(transactions) < response['total_investment_transactions'] - offset:
                     offset += len(transactions)
                else:
                    break

            # Also need initial holdings to work backward?
            # OR work forward from an empty state if we go back far enough?
            # Or work forward from a known "start" snapshot?
            # The prompt says: "Reconstruct end-of-day positions by applying transactions forward from an initial state."

            # We need the state AT start_date.
            # Plaid /investments/holdings/get returns CURRENT holdings.
            # If we have current holdings and ALL transactions since start_date, we can work BACKWARD.
            # Current - Transactions = Past.

            # Fetch Current Holdings
            from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest

            h_req = InvestmentsHoldingsGetRequest(access_token=access_token)
            h_res = self.plaid.investments_holdings_get(h_req)
            current_holdings = h_res['holdings']
            securities = {s['security_id']: s for s in h_res['securities']}

            # Map security_id to symbol
            sec_map = {}
            for s_id, s in securities.items():
                sec_map[s_id] = s.get('ticker_symbol') or s.get('name') or s_id

            # Build Positions Dict (Current)
            # {symbol: quantity}
            positions = {}
            for h in current_holdings:
                s_id = h['security_id']
                sym = sec_map.get(s_id)
                if not sym: continue
                positions[sym] = float(h['quantity'])

            # Sort transactions by date descending (newest first)
            all_transactions.sort(key=lambda x: x['date'], reverse=True)

            # We will iterate BACKWARDS in time:
            # Snapshot(Today) = Current Holdings.
            # Snapshot(Yesterday) = Snapshot(Today) - Buys + Sells.

            # Generate date range
            s_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            e_dt = datetime.strptime(end_date, "%Y-%m-%d").date()

            # We assume end_date is close to today or we have transactions up to today.
            # If end_date is in the past, we still need transactions from end_date to TODAY to bridge the gap.
            # Ideally we should fetch transactions from TODAY back to start_date.

            # For this MVP, let's assume we fetched up to Today (or close enough) if we use Plaid.
            # If the user asks for a range in the past, we need the bridge.
            # Let's assume the user calls this for a range ending today?
            # Or we fetch from start_date to NOW, but only save snapshots for start_date to end_date.

            # Let's re-fetch transactions up to NOW to be safe for backward reconstruction.
            # But the signature takes start/end.
            # If we use "Forward from initial state", we need the initial state (e.g. 0 if we start before account creation).
            # Working backward is usually more robust if we have current state.

            # Let's stick to Backward Reconstruction.

            curr_date = datetime.now().date()

            # Process transactions by day
            tx_by_day = {}
            for tx in all_transactions:
                d = tx['date']
                if d not in tx_by_day: tx_by_day[d] = []
                tx_by_day[d].append(tx)

            snapshots_created = 0

            # Iterate from Today backwards to start_date
            loop_date = curr_date

            # Current positions are valid for End of Today (roughly).
            # If we have transactions TODAY, we reverse them to get Start of Today (or End of Yesterday).

            while loop_date >= s_dt:
                # If loop_date is within requested range, save snapshot (End of Day state)
                if loop_date <= e_dt:
                    # Save 'positions' as snapshot for loop_date
                    self._save_snapshot(user_id, loop_date, positions)
                    snapshots_created += 1

                # Reverse transactions of this day to get state for previous day
                if loop_date in tx_by_day:
                    day_txs = tx_by_day[loop_date]
                    for tx in day_txs:
                        self._reverse_transaction(positions, tx, sec_map)

                loop_date -= timedelta(days=1)

            return snapshots_created

        except Exception as e:
            print(f"Error backfilling history: {e}")
            return 0

    def _get_access_token(self, user_id: str) -> Optional[str]:
        from services.token_store import PlaidTokenStore
        token_store = PlaidTokenStore(self.supabase)
        return token_store.get_access_token(user_id)

    def _reverse_transaction(self, positions: Dict[str, float], tx, sec_map):
        """
        Reverses the effect of a transaction on the position quantity.
        If we BOUGHT today, we had LESS yesterday.
        If we SOLD today, we had MORE yesterday.
        """
        s_id = tx['security_id']
        sym = sec_map.get(s_id)
        if not sym: return

        qty = float(tx['quantity'])
        type = tx['type']
        subtype = tx['subtype']

        # Plaid 'quantity' is positive for buy, positive for sell usually?
        # Check Plaid docs:
        # For 'buy', quantity is positive. cost_basis is positive (outflow).
        # For 'sell', quantity is positive.

        # If type is 'buy', we gained shares today. So yesterday we had (Current - Qty).
        # If type is 'sell', we lost shares today. So yesterday we had (Current + Qty).

        if type == 'buy':
            positions[sym] = positions.get(sym, 0) - qty
        elif type == 'sell':
            positions[sym] = positions.get(sym, 0) + qty

        # Handle Transfer?
        elif type == 'transfer':
            if subtype == 'in': # Received shares
                positions[sym] = positions.get(sym, 0) - qty
            elif subtype == 'out': # Sent shares
                positions[sym] = positions.get(sym, 0) + qty

        # Clean up near-zero
        if abs(positions.get(sym, 0)) < 1e-9:
             positions.pop(sym, None)

    def _save_snapshot(self, user_id: str, date_obj, positions_dict):
        # Construct holdings list
        holdings = []
        for sym, qty in positions_dict.items():
            holdings.append({
                "symbol": sym,
                "quantity": qty,
                "cost_basis": 0, # Historical cost basis hard to track without full history
                "current_price": 0, # We don't have historical price here easily
                "source": "backfill"
            })

        snapshot = {
            "user_id": user_id,
            "created_at": f"{date_obj.isoformat()}T23:59:59",
            "snapshot_type": "historical",
            "data_source": "plaid_backfill",
            "holdings": holdings,
            "buying_power": 0 # Placeholder
        }

        # Upsert based on user_id + created_at?
        # portfolio_snapshots doesn't have a unique constraint on (user_id, created_at) by default usually.
        # But we can try to avoid duplicates if possible.
        # Ideally we delete existing 'historical' snapshot for this day first?

        # Delete existing historical for this day
        # Time range for that day
        day_start = f"{date_obj.isoformat()}T00:00:00"
        day_end = f"{date_obj.isoformat()}T23:59:59"

        try:
            self.supabase.table("portfolio_snapshots").delete() \
                .eq("user_id", user_id) \
                .eq("snapshot_type", "historical") \
                .gte("created_at", day_start) \
                .lte("created_at", day_end) \
                .execute()

            self.supabase.table("portfolio_snapshots").insert(snapshot).execute()
        except Exception as e:
            print(f"Error saving snapshot for {date_obj}: {e}")
