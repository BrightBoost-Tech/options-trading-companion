"""
Plaid API Endpoints
"""
from fastapi import HTTPException
from typing import Dict
import json
import plaid
from plaid.exceptions import ApiException

def register_plaid_endpoints(app, plaid_service):
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
        """Exchange public token for access token"""
        try:
            public_token = request.get('public_token')
            if not public_token:
                raise HTTPException(status_code=400, detail="public_token required")
            
            result = plaid_service.exchange_public_token(public_token)
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
