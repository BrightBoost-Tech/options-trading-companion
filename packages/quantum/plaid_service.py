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

print(f"🔧 Plaid Service Init: Env={current_env}, Host={host_env}")

# Fetch and validate credentials
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET = os.getenv("PLAID_SECRET", "")

# Initialize Plaid Client
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
    """
    # Check if we have valid credentials to make a real call
    if not PLAID_SECRET or not PLAID_CLIENT_ID:
        if not PLAID_SECRET:
            print("⚠️  Plaid Secret missing - returning MOCK link token")
            return {"link_token": "link-sandbox-mock-token-123", "expiration": "2024-12-31T23:59:59Z"}
        raise ValueError("Missing PLAID_CLIENT_ID environment variable")

    if not user_id:
        raise ValueError("user_id is required for Plaid Link Token creation")

    try:
        client_user_id = str(user_id)

        request = LinkTokenCreateRequest(
            products=[Products.INVESTMENTS],
            client_name="Options Trading Companion",
            country_codes=[CountryCode.US],
            language='en',
            user=LinkTokenCreateRequestUser(
                client_user_id=client_user_id
            )
        )

        response = client.link_token_create(request)
        response_dict = response.to_dict()

        print(f"✅ Plaid Link Token Created: {response_dict.get('link_token', 'N/A')[:10]}...")
        return response_dict

    except plaid.ApiException as e:
        print(f"❌ Plaid API Error (Create Link Token): {e}")
        try:
            import json
            body = json.loads(e.body)
            print(f"   Error Code: {body.get('error_code')}")
            print(f"   Error Message: {body.get('error_message')}")
        except:
            pass
        raise e

def exchange_public_token(public_token: str):
    """
    Exchange public token for access token.
    """
    # Mock Handling
    if not PLAID_SECRET or public_token == "mock-public-token":
         print("⚠️  Returning MOCK access token")
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
    Get holdings wrapper.
    """
    if not PLAID_SECRET or access_token.startswith("access-sandbox-mock-"):
        print("⚠️  Returning MOCK holdings")
        holdings = _get_mock_holdings()
        return {"holdings": [h.dict() for h in holdings]}

    holdings = fetch_and_normalize_holdings(access_token)
    return {"holdings": [h.dict() for h in holdings]}

def fetch_and_normalize_holdings(access_token: str) -> list[Holding]:
    """
    Fetches holdings from Plaid and normalizes them into our internal Holding model.
    """
    # Mock Handling inside the fetcher logic too
    if not PLAID_SECRET or access_token.startswith("access-sandbox-mock-"):
        print("⚠️  Returning MOCK holdings (Internal Fetch)")
        return _get_mock_holdings()

    if not PLAID_CLIENT_ID:
        raise ValueError("Missing PLAID_CLIENT_ID environment variable")

    try:
        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = client.investments_holdings_get(request)

        holdings_data = response.get('holdings', [])
        securities_data = {s['security_id']: s for s in response.get('securities', [])}

        normalized_holdings = []

        for item in holdings_data:
            security_id = item.get('security_id')
            security = securities_data.get(security_id, {})

            ticker = security.get('ticker_symbol')
            if not ticker:
                continue

            qty = float(item.get('quantity', 0) or 0)
            cost_basis = float(item.get('cost_basis', 0) or 0)
            
            price = 0.0
            if security.get('close_price'):
                price = float(security.get('close_price'))
            elif item.get('institution_price'):
                price = float(item.get('institution_price'))

            holding = Holding(
                symbol=ticker,
                name=security.get('name'),
                quantity=qty,
                cost_basis=cost_basis,
                current_price=price,
                currency=item.get('iso_currency_code', 'USD'),
                institution_name="Plaid",
                source="plaid",
                account_id=item.get('account_id'),
                last_updated=datetime.now()
            )
            normalized_holdings.append(holding)

        return normalized_holdings

    except plaid.ApiException as e:
        print(f"Plaid API Error (Fetch Holdings): {e}")
        raise e

def _get_mock_holdings() -> list[Holding]:
    """Return a list of mock holdings for testing"""
    return [
        Holding(
            symbol="MOCK-AAPL",
            name="Mock Apple Inc",
            quantity=10.0,
            cost_basis=150.0,
            current_price=175.0,
            institution_name="Mock Broker",
            source="plaid",
            last_updated=datetime.now()
        ),
        Holding(
            symbol="MOCK-SPY",
            name="Mock SPDR S&P 500",
            quantity=5.0,
            cost_basis=400.0,
            current_price=450.0,
            institution_name="Mock Broker",
            source="plaid",
            last_updated=datetime.now()
        )
    ]
