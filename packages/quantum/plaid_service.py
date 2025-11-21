import os
import plaid
from datetime import datetime
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from models import Holding

# Get the current environment (default to sandbox)
current_env = os.getenv("PLAID_ENV", "sandbox").lower().strip()

# Map to Plaid Environment Enum
host_env = plaid.Environment.Sandbox
if current_env == 'development':
    host_env = plaid.Environment.Development
elif current_env == 'production':
    host_env = plaid.Environment.Production

# Initialize Plaid Client
configuration = plaid.Configuration(
    host=host_env,
    api_key={
        'clientId': os.getenv("PLAID_CLIENT_ID") or "",
        'secret': os.getenv("PLAID_SECRET") or "",
    }
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

def create_link_token(user_id: str):
    """
    Create a link token for a given user.
    If in sandbox/dev with no real keys, return a mock token.
    """
    if not os.getenv("PLAID_SECRET"):
        # MOCK MODE for local dev if no secret
        print("⚠️  Plaid Secret missing - returning MOCK link token")
        return {"link_token": "link-sandbox-mock-token-123", "expiration": "2024-12-31T23:59:59Z"}

    try:
        request = LinkTokenCreateRequest(
            products=[Products('investments')],
            client_name="Options Trading Companion",
            country_codes=[CountryCode('US')],
            language='en',
            user=LinkTokenCreateRequestUser(
                client_user_id=user_id
            )
        )
        response = client.link_token_create(request)
        return response.to_dict()
    except plaid.ApiException as e:
        print(f"Plaid API Error (Create Link Token): {e}")
        raise e

def exchange_public_token(public_token: str):
    """
    Exchange public token for access token.
    """
    if not os.getenv("PLAID_SECRET"):
         print("⚠️  Plaid Secret missing - returning MOCK access token")
         return {"access_token": "access-sandbox-mock-token-123", "item_id": "mock-item-id"}

    try:
        request = ItemPublicTokenExchangeRequest(
            public_token=public_token
        )
        response = client.item_public_token_exchange(request)
        return response.to_dict()
    except plaid.ApiException as e:
        print(f"Plaid API Error (Exchange Token): {e}")
        raise e

def get_holdings(access_token: str):
    """
    Get holdings wrapper (calls fetch_and_normalize_holdings but returns dict for endpoint).
    """
    if not os.getenv("PLAID_SECRET"):
        print("⚠️  Plaid Secret missing - returning MOCK holdings")
        return {"holdings": [{"symbol": "MOCK", "quantity": 10, "price": 100}]}

    holdings = fetch_and_normalize_holdings(access_token)
    return {"holdings": [h.dict() for h in holdings]}

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
