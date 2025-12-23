"""
Plaid API Endpoints
"""
from fastapi import HTTPException, Header, Depends, Body, Request
from typing import Dict, Optional
import json
import plaid
from plaid.exceptions import ApiException
from datetime import datetime
from packages.quantum.security import encrypt_token, decrypt_token, redact_sensitive_fields, get_current_user
from supabase import Client
from slowapi import Limiter

def parse_plaid_error(e: ApiException) -> str:
    """Helper to extract readable error message from Plaid ApiException"""
    try:
        # body is usually a JSON string
        error_body = json.loads(e.body)
        return f"Plaid Error: {error_body.get('error_message')} ({error_body.get('error_code')})"
    except Exception:
        return f"Plaid API Error: {str(e)}"

def register_plaid_endpoints(
    app,
    plaid_service,
    supabase_admin: Client,
    analytics_service,
    # dependency injection
    get_supabase_client_dependency,
    limiter: Limiter
):
    """Register Plaid endpoints with the FastAPI app"""
    
    if not plaid_service:
        print("⚠️  Plaid service not available - endpoints disabled")
        return

    @app.get("/plaid/status")
    async def get_plaid_status(
        user_id: str = Depends(get_current_user),
        supabase: Client = Depends(get_supabase_client_dependency)
    ):
        """Check if user has a connected Plaid account"""
        try:
            if not supabase:
                return {"connected": False, "institution": None, "error": "Database not available"}

            # Check user_settings
            res = supabase.table("user_settings").select("plaid_access_token, plaid_institution").eq("user_id", user_id).single().execute()

            if res.data and res.data.get('plaid_access_token'):
                return {
                    "connected": True,
                    "institution": res.data.get('plaid_institution') or "Connected Broker"
                }

            return {"connected": False, "institution": None}

        except Exception as e:
            print(f"❌ Error checking Plaid status: {e}")
            return {"connected": False, "institution": None}

    @app.post("/plaid/create_link_token")
    @limiter.limit("10/minute")
    async def create_plaid_link_token(
        request: Request,
        user_id: str = Depends(get_current_user)
    ):
        """Create Plaid Link token for connecting brokerage account"""
        if analytics_service:
            analytics_service.log_event(user_id, "plaid_link_started", "ux", {})

        try:
            result = plaid_service.create_link_token(user_id)
            return redact_sensitive_fields(result)
        except ValueError as e:
            print(f"❌ Plaid Configuration Error: {e}")
            if analytics_service:
                analytics_service.log_event(user_id, "plaid_link_error", "system", {"error": str(e)})
            raise HTTPException(status_code=400, detail=str(e))
        except ApiException as e:
            error_msg = parse_plaid_error(e)
            print(f"❌ Plaid Link Token Error: {error_msg}")
            if analytics_service:
                analytics_service.log_event(user_id, "plaid_link_error", "system", {"error": error_msg})
            raise HTTPException(status_code=400, detail=error_msg)
        except Exception as e:
            print(f"❌ Unexpected Error in create_link_token: {e}")
            if analytics_service:
                analytics_service.log_event(user_id, "plaid_link_error", "system", {"error": str(e)})
            # SECURITY: Do not leak exception details in 500 responses
            raise HTTPException(status_code=500, detail="Internal Server Error: Failed to create link token.")

    @app.post("/plaid/exchange_token")
    @limiter.limit("5/minute")
    async def exchange_plaid_token(
        request: Request,
        public_token: str = Body(..., embed=True),
        metadata: Dict = Body({}, embed=True),
        user_id: str = Depends(get_current_user),
        supabase: Client = Depends(get_supabase_client_dependency)
    ):
        """Exchange public token for access token and store it"""
        try:
            print(f"🔄 Exchanging public token for user {user_id}...")
            result = plaid_service.exchange_public_token(public_token)

            if analytics_service:
                analytics_service.log_event(user_id, "plaid_link_completed", "ux", {"institution": metadata.get("institution", {}).get("name")})

            access_token = result.get('access_token')

            if access_token and supabase:
                print(f"💾 Saving Plaid credentials for user {user_id}")
                from packages.quantum.services.token_store import PlaidTokenStore
                token_store = PlaidTokenStore(supabase)

                # Metadata enrichment
                if result.get('item_id'):
                    metadata['item_id'] = result.get('item_id')

                token_store.save_access_token(user_id, access_token, metadata)

            return redact_sensitive_fields(result)

        except ValueError as e:
            print(f"❌ Plaid Configuration Error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except ApiException as e:
            error_msg = parse_plaid_error(e)
            print(f"❌ Plaid Exchange Token Error: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        except Exception as e:
            print(f"❌ Unexpected Error in exchange_token: {e}")
            # SECURITY: Do not leak exception details
            raise HTTPException(status_code=500, detail="Internal Server Error: Token exchange failed.")

    @app.post("/plaid/sync_holdings")
    @limiter.limit("5/minute")
    async def sync_plaid_holdings(
        request: Request,
        user_id: str = Depends(get_current_user),
        supabase: Client = Depends(get_supabase_client_dependency)
    ):
        """Sync holdings from connected brokerage account and store them"""
        try:
            if not supabase:
                 raise HTTPException(status_code=503, detail="Database not available")

            # Look up token
            print(f"🔍 Looking up access token for user {user_id}")
            from packages.quantum.services.token_store import PlaidTokenStore
            token_store = PlaidTokenStore(supabase)
            access_token = token_store.get_access_token(user_id)

            if not access_token:
                 raise HTTPException(status_code=404, detail="No linked Plaid account")
            
            # Fetch from Plaid
            print("Fetching holdings from Plaid Service...")
            result = plaid_service.get_holdings(access_token)
            holdings_list = result.get('holdings', [])

            # Upsert to positions table
            if holdings_list:
                print(f"💾 Saving {len(holdings_list)} positions for user {user_id}")
                positions_to_insert = []
                for h in holdings_list:
                    positions_to_insert.append({
                        "user_id": user_id,
                        "symbol": h.get('symbol'),
                        "quantity": h.get('quantity'),
                        "cost_basis": h.get('cost_basis'),
                        "current_price": h.get('current_price'),
                        "currency": h.get('currency'),
                        "source": "plaid",
                        "updated_at": datetime.now().isoformat()
                    })

                try:
                    supabase.table("positions").upsert(
                        positions_to_insert,
                        on_conflict="user_id,symbol"
                    ).execute()
                    print("✅ Positions updated in DB")
                except Exception as e:
                    print(f"❌ Failed to update positions in DB: {e}")
                    raise HTTPException(status_code=500, detail="Database update failed.")

            return {
                "status": "ok",
                "holdings_count": len(holdings_list),
                "source": "plaid"
            }

        except ValueError as e:
            print(f"❌ Plaid Configuration Error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except ApiException as e:
            error_msg = parse_plaid_error(e)
            print(f"❌ Plaid Holdings Error: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        except Exception as e:
            print(f"❌ Unexpected Error in get_holdings: {e}")
            # SECURITY: Do not leak exception details
            raise HTTPException(status_code=500, detail="Internal Server Error: Failed to retrieve holdings.")
    
    print("✅ Plaid endpoints registered (v3 Hardened)")
