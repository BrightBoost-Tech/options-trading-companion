import os
from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest
from models import Holding
from market_data import get_polygon_price
from security import encrypt_token, decrypt_token
from database import supabase
from datetime import datetime

load_dotenv()

class PlaidService:
    def __init__(self):
        # PLAID_ENV controls which Plaid host is used (sandbox, development, production).
        # PLAID_SECRET must match the key for the selected environment.
        self.PLAID_CLIENT_ID = os.getenv("PLAID_CLIENT_ID")
        self.PLAID_SECRET = os.getenv("PLAID_SECRET")
        self.PLAID_ENV = os.getenv("PLAID_ENV", "sandbox").strip().lower()

        if self.PLAID_ENV == "development":
            host = plaid.Environment.Development
        elif self.PLAID_ENV == "production":
            host = plaid.Environment.Production
        else:
            host = plaid.Environment.Sandbox

        print(f"💳 Plaid Service Initialized in: {self.PLAID_ENV.upper()} mode")

        configuration = plaid.Configuration(
            host=host,
            api_key={
                'clientId': self.PLAID_CLIENT_ID,
                'secret': self.PLAID_SECRET,
            }
        )
        api_client = plaid.ApiClient(configuration)
        self.client = plaid_api.PlaidApi(api_client)

    def create_link_token(self, user_id: str):
        if not self.PLAID_SECRET or not self.PLAID_CLIENT_ID:
            return "link-sandbox-mock-token-123"

        request = LinkTokenCreateRequest(
            products=[Products('investments')],
            client_name="Options Trading Companion",
            country_codes=[CountryCode('US')],
            language='en',
            user=LinkTokenCreateRequestUser(client_user_id=str(user_id))
        )
        response = self.client.link_token_create(request)
        return response['link_token']

    def exchange_public_token(self, public_token: str):
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = self.client.item_public_token_exchange(request)
        return response['access_token']

    def store_access_token(self, user_id: str, access_token: str):
        encrypted_token = encrypt_token(access_token)
        supabase.table('user_settings').upsert({
            "user_id": user_id,
            "plaid_access_token": encrypted_token
        }, on_conflict="user_id").execute()

    def get_access_token(self, user_id: str):
        response = supabase.table('user_settings').select("plaid_access_token").eq("user_id", user_id).execute()
        if response.data:
            encrypted_token = response.data[0]['plaid_access_token']
            return decrypt_token(encrypted_token)
        return None

    def get_holdings(self, access_token: str):
        request = InvestmentsHoldingsGetRequest(access_token=access_token)
        response = self.client.investments_holdings_get(request)
        return self._normalize_holdings(response.to_dict())

    def _normalize_holdings(self, data):
        holdings = data.get('holdings', [])
        securities = {s['security_id']: s for s in data.get('securities', [])}
        normalized = []
        for h in holdings:
            sec = securities.get(h['security_id'], {})
            symbol = sec.get('ticker_symbol') or h.get('unofficial_currency_code')
            if not symbol:
                continue

            current_price = get_polygon_price(symbol)
            normalized.append(
                Holding(
                    symbol=symbol,
                    name=sec.get('name'),
                    quantity=h['quantity'],
                    cost_basis=h['cost_basis'],
                    current_price=current_price or sec.get('close_price') or 0,
                    currency=h['iso_currency_code'],
                    last_updated=datetime.now()
                ).dict()
            )
        return normalized

