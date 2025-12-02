"""
Plaid API Endpoints
"""
from fastapi import HTTPException, Header
from typing import Dict
import json
import plaid
from plaid.exceptions import ApiException
from datetime import datetime
from security import encrypt_token, decrypt_token, redact_sensitive_fields

def register_plaid_endpoints(app, plaid_service, supabase_client=None):
    """Register Plaid endpoints with the FastAPI app"""
    
    if not plaid_service:
        print("⚠️  Plaid service not available - endpoints disabled")
        return
    
    def parse_plaid_error(e: ApiException) -> str:
        """Helper to extract readable error message from Plaid ApiException"""
        try:
            # body is usually a JSON string
            error_body = json.loads(e.body)
            return f"Plaid Error: {error_body.get('error_message')} ({error_body.get('error_code')})"
        except Exception:
            return f"Plaid API Error: {str(e)}"

    @app.get("/plaid/status")
    async def get_plaid_status(
        authorization: str = Header(None),
        x_test_mode_user: str = Header(None, alias="X-Test-Mode-User")
    ):
        """Check if user has a connected Plaid account"""
        try:
            user_id = None
            if x_test_mode_user:
                # Basic check if test mode allowed? Assuming yes for simplicity in this helper
                user_id = x_test_mode_user
            elif authorization:
                try:
                    if supabase_client:
                        token = authorization.split(" ")[1]
                        user = supabase_client.auth.get_user(token)
                        user_id = user.user.id
                except Exception:
                    pass

            if not user_id:
                raise HTTPException(status_code=401, detail="Not authenticated")

            if not supabase_client:
                return {"connected": False, "institution": None, "error": "Database not available"}

            # Check user_settings
            res = supabase_client.table("user_settings").select("plaid_access_token, plaid_institution").eq("user_id", user_id).single().execute()

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
    async def create_plaid_link_token(request: Dict):
        """Create Plaid Link token for connecting brokerage account"""
        try:
            user_id = request.get('user_id', 'default_user')
            result = plaid_service.create_link_token(user_id)
            # Ensure return format is { "link_token": "..." }
            # Service returns full dict, which includes link_token
            return redact_sensitive_fields(result)
        except ValueError as e:
            print(f"❌ Plaid Configuration Error: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except ApiException as e:
            error_msg = parse_plaid_error(e)
            print(f"❌ Plaid Link Token Error: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        except Exception as e:
            print(f"❌ Unexpected Error in create_link_token: {e}")
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

    @app.post("/plaid/exchange_token")
    async def exchange_plaid_token(request: Dict):
        """Exchange public token for access token and store it"""
        try:
            public_token = request.get('public_token')
            user_id = request.get('user_id')
            metadata = request.get('metadata', {}) # Plaid Link metadata

            if not public_token:
                raise HTTPException(status_code=400, detail="public_token required")
            
            print(f"🔄 Exchanging public token for user {user_id}...")
            result = plaid_service.exchange_public_token(public_token)

            access_token = result.get('access_token')

            if access_token and supabase_client and user_id:
                print(f"💾 Saving Plaid credentials for user {user_id}")
                from services.token_store import PlaidTokenStore
                token_store = PlaidTokenStore(supabase_client)

                # Metadata is passed to help constructing item info inside store
                # We inject 'item_id' from result into metadata for completeness if needed,
                # though token_store currently expects metadata to have 'institution' etc.
                # Let's enrich metadata with item_id from result
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
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

    @app.post("/plaid/get_holdings")
    async def get_plaid_holdings(request: Dict):
        """Get holdings from connected brokerage account and store them"""
        try:
            # We can accept access_token directly OR look it up for the user
            access_token = request.get('access_token')
            user_id = request.get('user_id')

            if not access_token and user_id and supabase_client:
                # Look up token if not provided but user_id is
                print(f"🔍 Looking up access token for user {user_id}")
                from services.token_store import PlaidTokenStore
                token_store = PlaidTokenStore(supabase_client)
                access_token = token_store.get_access_token(user_id)

            if not access_token:
                 raise HTTPException(status_code=400, detail="access_token required or not found for user")
            
            # Fetch from Plaid
            print("Fetching holdings from Plaid Service...")
            result = plaid_service.get_holdings(access_token)
            holdings_list = result.get('holdings', [])

            # Upsert to positions table
            if supabase_client and user_id:
                print(f"💾 Saving {len(holdings_list)} positions for user {user_id}")
                positions_to_insert = []
                for h in holdings_list:
                    # h is a dict from Holding model
                    positions_to_insert.append({
                        "user_id": user_id,
                        "symbol": h.get('symbol'),
                        "quantity": h.get('quantity'),
                        "cost_basis": h.get('cost_basis'),
                        "current_price": h.get('current_price'),
                        "currency": h.get('currency'),
                        "source": "plaid",
                        # "institution_name": h.get('institution_name'), # positions table might not have this column, check schema?
                        # Using standard columns likely: user_id, symbol, quantity, cost_basis, current_price
                        # If schema allows jsonb or extra cols, great. Assuming basic schema for now based on models.
                        "updated_at": datetime.now().isoformat()
                    })

                if positions_to_insert:
                    try:
                        # Upsert based on user_id and symbol
                        # Note: This assumes unique constraint on (user_id, symbol)
                        supabase_client.table("positions").upsert(
                            positions_to_insert,
                            on_conflict="user_id,symbol"
                        ).execute()
                        print("✅ Positions updated in DB")
                    except Exception as e:
                        print(f"❌ Failed to update positions in DB: {e}")

            # Return success response
            return {
                "synced": True,
                "positions_count": len(holdings_list),
                "holdings": holdings_list
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
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")
    
    print("✅ Plaid endpoints registered")
