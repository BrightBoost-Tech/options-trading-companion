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

# Fetch and validate credentials
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")

# If using MOCK mode (no secret), we don't need to initialize the real client fully,
# or we can initialize it with dummy values to avoid NoneType errors.
# But if we have a secret, we MUST have a client ID.
if PLAID_SECRET and not PLAID_CLIENT_ID:
    print("⚠️  PLAID_SECRET is set but PLAID_CLIENT_ID is missing. Plaid calls will fail.")

# Initialize Plaid Client
# Ensure we never pass None to api_key values
configuration = plaid.Configuration(
    host=host_env,
    api_key={
        'clientId': PLAID_CLIENT_ID or "dummy_client_id",
        'secret': PLAID_SECRET or "dummy_secret",
    }
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

def create_link_token(user_id: str):
    """
    Create a link token for a given user.
    If in sandbox/dev with no real keys, return a mock token.
    """
    # Check if we have valid credentials to make a real call
    # We need BOTH Client ID and Secret.
    if not PLAID_SECRET or not PLAID_CLIENT_ID:
        if not PLAID_SECRET:
            # MOCK MODE for local dev if no secret
            print("⚠️  Plaid Secret missing - returning MOCK link token")
            return {"link_token": "link-sandbox-mock-token-123", "expiration": "2024-12-31T23:59:59Z"}

        # If we have secret but no client ID, this is a configuration error
        raise ValueError("Missing PLAID_CLIENT_ID environment variable")

    if not user_id:
        raise ValueError("user_id is required for Plaid Link Token creation")

    try:
        # Use Enum values for Products and CountryCode to ensure correct serialization
        # Products.INVESTMENTS maps to "investments"
        # CountryCode.US maps to "US"

        # Note: redirect_uri is often required for OAuth institutions (most US banks now).
        # However, it requires whitelisting in Plaid Dashboard.
        # If missing, Link might fail for OAuth banks.
        # For now, we leave it out as requested, assuming "investments" product in Sandbox works without it.

        request = LinkTokenCreateRequest(
            products=[Products.INVESTMENTS],
            client_name="Options Trading Companion",
            country_codes=[CountryCode.US],
            language='en',
            user=LinkTokenCreateRequestUser(
                client_user_id=str(user_id) # Ensure string
            )
        )

        # Debug log request (excluding sensitive user info if any)
        print(f"Creating Plaid Link Token for user {user_id}...")

        response = client.link_token_create(request)
        response_dict = response.to_dict()

        print(f"✅ Plaid Link Token Created: {response_dict.get('link_token', 'N/A')[:10]}...")
        return response_dict

    except plaid.ApiException as e:
        print(f"Plaid API Error (Create Link Token): {e}")
        raise e

def exchange_public_token(public_token: str):
    """
    Exchange public token for access token.
    """
    if not PLAID_SECRET:
         print("⚠️  Plaid Secret missing - returning MOCK access token")
         return {"access_token": "access-sandbox-mock-token-123", "item_id": "mock-item-id"}

    if not PLAID_CLIENT_ID:
         raise ValueError("Missing PLAID_CLIENT_ID environment variable")

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
    if not PLAID_SECRET:
        print("⚠️  Plaid Secret missing - returning MOCK holdings")
        return {"holdings": [{"symbol": "MOCK", "quantity": 10, "price": 100}]}

    holdings = fetch_and_normalize_holdings(access_token)
    return {"holdings": [h.dict() for h in holdings]}

def fetch_and_normalize_holdings(access_token: str) -> list[Holding]:
    """
    Fetches holdings from Plaid and normalizes them into our internal Holding model.
    """
    if not PLAID_CLIENT_ID:
        raise ValueError("Missing PLAID_CLIENT_ID environment variable")

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
