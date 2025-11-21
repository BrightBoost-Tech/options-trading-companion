import os
import plaid
from datetime import datetime
from plaid.api import plaid_api
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from models import Holding

# Define Plaid Environments manually to avoid AttributeError
PLAID_ENVIRONMENTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com"
}

# Get the current environment (default to sandbox)
# FIX: Added .strip() to remove any accidental whitespace from the .env file
current_env = os.getenv("PLAID_ENV", "sandbox").lower().strip()
plaid_host = PLAID_ENVIRONMENTS.get(current_env)

if not plaid_host:
    # Debug print to see exactly what is being read if it fails again
    print(f"DEBUG: Loaded PLAID_ENV='{current_env}'") 
    raise ValueError(f"Invalid PLAID_ENV: '{current_env}'. Must be one of: {list(PLAID_ENVIRONMENTS.keys())}")

# Initialize Plaid Client
configuration = plaid.Configuration(
    host=plaid_host,
    api_key={
        'clientId': os.getenv("PLAID_CLIENT_ID") or "",
        'secret': os.getenv("PLAID_SECRET") or "",
    }
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

def fetch_and_normalize_holdings(access_token: str) -> list[Holding]:
    """
    Fetches holdings from Plaid and normalizes them into our internal Holding model.
    """
    try:
        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = client.investments_holdings_get(request)

        holdings_data = response.get('holdings', [])
        securities_data = {s['security_id']: s for s in response.get('securities', [])}
        # accounts_data = {a['account_id']: a for a in response.get('accounts', [])} # Not used yet but available

        normalized_holdings = []

        for item in holdings_data:
            security_id = item.get('security_id')
            security = securities_data.get(security_id, {})

            # Skip if no ticker symbol (e.g., cash positions often lack symbols)
            if not security.get('ticker_symbol'):
                continue

            # Handle potential None values safely
            qty = float(item.get('quantity', 0) or 0)
            cost_basis = float(item.get('cost_basis', 0) or 0)
            
            # Price priority: Close price -> Institution Price -> 0
            price = 0.0
            if security.get('close_price'):
                price = float(security.get('close_price'))
            elif item.get('institution_price'):
                price = float(item.get('institution_price'))

            holding = Holding(
                symbol=security.get('ticker_symbol'),
                name=security.get('name'),
                quantity=qty,
                cost_basis=cost_basis,
                current_price=price,
                currency=item.get('iso_currency_code', 'USD'),
                source="plaid",
                account_id=item.get('account_id'),
                last_updated=datetime.now()
            )
            normalized_holdings.append(holding)

        return normalized_holdings

    except plaid.ApiException as e:
        print(f"Plaid API Error: {e}")
        raise e
