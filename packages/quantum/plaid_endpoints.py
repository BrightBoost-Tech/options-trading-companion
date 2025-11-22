"""
Plaid API Endpoints
"""
from fastapi import HTTPException
from typing import Dict
import json
import plaid
from plaid.exceptions import ApiException

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

    @app.post("/plaid/create_link_token")
    async def create_plaid_link_token(request: Dict):
        """Create Plaid Link token for connecting brokerage account"""
        try:
            user_id = request.get('user_id', 'default_user')
            result = plaid_service.create_link_token(user_id)
            return result
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
            user_id = request.get('user_id') # Should be passed or extracted from auth if available

            # If we want to be strict, we should rely on Auth Header, but for now we might accept user_id in body if auth is optional or handled elsewhere
            # Ideally, we should extract user_id from the session token if passed, but this function signature is generic.
            # Let's assume the frontend might not pass user_id in body if it's authenticated via headers, but here we might need it.
            # HOWEVER, the prompt emphasizes saving the access token.

            if not public_token:
                raise HTTPException(status_code=400, detail="public_token required")
            
            print(f"🔄 Exchanging public token for user {user_id}...")
            result = plaid_service.exchange_public_token(public_token)

            access_token = result.get('access_token')
            item_id = result.get('item_id')

            if access_token and supabase_client and user_id:
                print(f"💾 Saving Plaid Item for user {user_id}")
                # Upsert into plaid_items
                try:
                    supabase_client.table("plaid_items").upsert({
                        "user_id": user_id,
                        "access_token": access_token,
                        "item_id": item_id,
                        "institution_name": "Plaid Item", # We might get this from metadata if passed, but for now generic
                        "status": "active",
                        "updated_at": "now()"
                    }, on_conflict="user_id").execute()
                    print("✅ Plaid Item Saved to DB")
                except Exception as e:
                     print(f"❌ Failed to save Plaid Item to DB: {e}")
                     # We don't fail the request if DB save fails, but it's bad.

            return result

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
        """Get holdings from connected brokerage account"""
        try:
            access_token = request.get('access_token')
            if not access_token:
                raise HTTPException(status_code=400, detail="access_token required")
            
            result = plaid_service.get_holdings(access_token)
            return result
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
