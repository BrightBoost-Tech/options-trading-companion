import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# --- FORCE LOAD .ENV ---
# Explicitly target the .env file in the same directory as this script
env_path = Path(__file__).resolve().parent / ".env"

print("!" * 60)
print(f"🕵️  PLAID SERVICE: Loading environment configuration...")
print(f"📍  Targeting .env path: {env_path}")
print(f"📂  File exists? {env_path.exists()}")

# Force load the specific .env file
load_dotenv(dotenv_path=env_path, override=True)

# Interrogate loaded values
current_plaid_env = os.getenv("PLAID_ENV")
plaid_secret = os.getenv("PLAID_SECRET")
plaid_secret_preview = plaid_secret[:4] if plaid_secret else "NONE"

print(f"🌍  PLAID_ENV: {current_plaid_env}")
print(f"🔑  PLAID_SECRET (first 4): {plaid_secret_preview}")
print("!" * 60)
# -----------------------

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
from market_data import get_polygon_price

# 1. Verify and correct backend environment mapping
current_env_str = (current_plaid_env or "sandbox").lower().strip()

if current_env_str == "development":
    # ✅ FIX: Use the Production URL for Development keys
    host_env = "https://production.plaid.com"  
    env_log_msg = "Plaid environment: DEVELOPMENT (Using Production URL)"
elif current_env_str == "production":
    host_env = "https://production.plaid.com"
    env_log_msg = "Plaid environment: PRODUCTION"
else:
    host_env = "https://sandbox.plaid.com"
    env_log_msg = f"Plaid environment: SANDBOX (configured: {current_env_str})"

# Fetch credentials
PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
PLAID_SECRET = plaid_secret # Already loaded

# Startup Logging
print("-" * 40)
print(env_log_msg)
if PLAID_CLIENT_ID and PLAID_SECRET:
    print(f"Using Plaid {current_env_str} keys")
else:
    print("⚠️  MISSING Plaid Credentials. Plaid Link will not work correctly.")
    if not PLAID_CLIENT_ID: print("   - PLAID_CLIENT_ID is missing")
    if not PLAID_SECRET: print("   - PLAID_SECRET is missing")
print("-" * 40)

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
    # DEBUG: Check what the function actually sees
    print(f"🕵️ DEBUG: PLAID_CLIENT_ID exists? {bool(PLAID_CLIENT_ID)}")
    print(f"🕵️ DEBUG: PLAID_SECRET exists? {bool(PLAID_SECRET)}")

    # Check if we have valid credentials to make a real call
    if not PLAID_SECRET or not PLAID_CLIENT_ID:
        raise ValueError("Missing PLAID_CLIENT_ID or PLAID_SECRET environment variable")

    if not user_id:
        raise ValueError("user_id is required for Plaid Link Token creation")

    try:
        client_user_id = str(user_id)

        # 3. Update /plaid/create_link_token to generate a link token for Investments
        request = LinkTokenCreateRequest(
            products=[Products('investments')], 
            client_name="Options Trading Companion",
            country_codes=[CountryCode('US')], 
            language='en',
            user=LinkTokenCreateRequestUser(
                client_user_id=client_user_id
            )
        )

        response = client.link_token_create(request)
        response_dict = response.to_dict()

        print(f"✅ Plaid Link Token Created: {response_dict.get('link_token', 'N/A')[:10]}...")
        # Return exact JSON structure as requested
        return {"link_token": response_dict.get("link_token")}

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
    if not PLAID_SECRET:
         raise ValueError("Missing PLAID_SECRET environment variable")

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
    if not PLAID_SECRET:
        raise ValueError("Missing PLAID_SECRET environment variable")

    holdings = fetch_and_normalize_holdings(access_token)
    return {"holdings": [h.dict() for h in holdings]}

def fetch_and_normalize_holdings(access_token: str) -> list[Holding]:
    """
    Fetches holdings from Plaid and normalizes them into our internal Holding model.
    """
    # Mock Handling inside the fetcher logic too
    if not PLAID_SECRET:
        raise ValueError("Missing PLAID_SECRET environment variable")

    if not PLAID_CLIENT_ID:
        raise ValueError("Missing PLAID_CLIENT_ID environment variable")

    try:
        # 4. Ensure holdings sync uses the investments endpoint
        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = client.investments_holdings_get(request)

        holdings_data = response.get('holdings', [])
        securities_data = {s['security_id']: s for s in response.get('securities', [])}

        normalized_holdings = []

        for item in holdings_data:
            security_id = item.get('security_id')
            security = securities_data.get(security_id, {})

            ticker = security.get('ticker_symbol')
            # Fallback to name if ticker is missing, or skip? Prompt implies we match security.
            # "For each holding in holdings, find the corresponding security to get its ticker_symbol"
            # "symbol – use the security’s ticker if available (or a composite name if no ticker...)"
            if not ticker:
                ticker = security.get('name', 'Unknown')

            qty = float(item.get('quantity', 0) or 0)
            cost_basis = float(item.get('cost_basis', 0) or 0)
            
            # Fetch real price from Polygon if available
            price = get_polygon_price(ticker)

            if price == 0.0:
                if security.get('close_price'):
                    price = float(security.get('close_price'))
                elif item.get('institution_price'):
                    price = float(item.get('institution_price'))

            # Fallback to institution value / quantity if price missing?
            # Plaid usually provides institution_price.

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
