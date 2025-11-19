"""
Plaid API Endpoints
"""
from fastapi import HTTPException
from typing import Dict

def register_plaid_endpoints(app, plaid_service):
    """Register Plaid endpoints with the FastAPI app"""
    
    if not plaid_service:
        print("⚠️  Plaid service not available - endpoints disabled")
        return
    
    @app.post("/plaid/create_link_token")
    async def create_plaid_link_token(request: Dict):
        """Create Plaid Link token for connecting brokerage account"""
        try:
            user_id = request.get('user_id', 'default_user')
            result = plaid_service.create_link_token(user_id)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/plaid/exchange_token")
    async def exchange_plaid_token(request: Dict):
        """Exchange public token for access token"""
        try:
            public_token = request.get('public_token')
            if not public_token:
                raise HTTPException(status_code=400, detail="public_token required")
            
            result = plaid_service.exchange_public_token(public_token)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/plaid/get_holdings")
    async def get_plaid_holdings(request: Dict):
        """Get holdings from connected brokerage account"""
        try:
            access_token = request.get('access_token')
            if not access_token:
                raise HTTPException(status_code=400, detail="access_token required")
            
            result = plaid_service.get_holdings(access_token)
            return result
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    print("✅ Plaid endpoints registered")
