import os
import requests
import hmac
import hashlib
import base64
import time
from typing import List, Dict, Optional
from datetime import datetime
from models import Holding

class SnapTradeClient:
    def __init__(self):
        self.client_id = os.getenv("SNAPTRADE_CLIENT_ID")
        self.consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY")
        # Default to production if not specified, as SnapTrade doesn't seem to have a "sandbox" URL for base API in the same way Plaid does
        self.base_url = os.getenv("SNAPTRADE_BASE_URL", "https://api.snaptrade.com/api/v1")

        if not self.client_id or not self.consumer_key:
            print("⚠️  SnapTrade credentials missing. Client initialized in MOCK mode.")
            self.is_mock = True
        else:
            self.is_mock = False

    def _get_headers(self, user_id: str = None, user_secret: str = None):
        """
        Constructs headers for SnapTrade API requests.
        For many endpoints, simply passing clientId and consumerKey as query params is supported,
        but the Python SDK / examples often show them in params.
        The documentation says "Authorization: clientId *. consumerKey *".

        Some endpoints require signature.
        However, for simplicity and based on common integration patterns:
        - We will pass clientId and consumerKey in query params for basic auth requests.
        - For user-specific requests, we might need userSecret.
        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _get_params(self):
        return {
            "clientId": self.client_id,
            "consumerKey": self.consumer_key
        }

    def register_user(self, internal_user_id: str) -> Dict[str, str]:
        """
        Registers a new user on SnapTrade or retrieves existing one.
        Returns: {"userId": "...", "userSecret": "..."}
        """
        if self.is_mock:
            return {"userId": f"snap-{internal_user_id}", "userSecret": "mock-secret"}

        url = f"{self.base_url}/snapTrade/registerUser"
        payload = {"userId": internal_user_id}

        try:
            # Check if we already have this user saved in our DB?
            # The caller is responsible for storage. We just call the API.
            # Note: SnapTrade returns existing user secret if registered again with same userId.

            response = requests.post(url, params=self._get_params(), json=payload)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"SnapTrade Register User Error: {e}")
            if e.response:
                print(e.response.text)
            raise

    def get_connection_url(self, user_id: str, user_secret: str) -> str:
        """
        Generates a redirect URI for the user to connect their brokerage.
        """
        if self.is_mock:
            return "https://app.snaptrade.com/demo/connect"

        url = f"{self.base_url}/snapTrade/login"
        params = self._get_params()
        params['userId'] = user_id
        params['userSecret'] = user_secret

        try:
            response = requests.post(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("redirectURI")
        except requests.RequestException as e:
            print(f"SnapTrade Login Error: {e}")
            raise

    def get_accounts(self, user_id: str, user_secret: str) -> List[Dict]:
        """
        Returns list of brokerage accounts for the user.
        """
        if self.is_mock:
            return [{
                "id": "mock-account-id",
                "name": "Robinhood Mock",
                "number": "123456789",
                "institution_name": "Robinhood"
            }]

        url = f"{self.base_url}/accounts"
        params = self._get_params()
        params['userId'] = user_id
        params['userSecret'] = user_secret

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"SnapTrade Get Accounts Error: {e}")
            raise

    def get_account_holdings(self, user_id: str, user_secret: str, account_id: str) -> List[Dict]:
        """
        Returns holdings (positions) for a specific account.
        """
        if self.is_mock:
            return [{
                "symbol": {
                    "symbol": "TSLA",
                    "description": "Tesla Inc",
                    "currency": {"code": "USD"}
                },
                "units": 10,
                "price": 250.0,
                "average_purchase_price": 200.0
            }]

        url = f"{self.base_url}/accounts/{account_id}/holdings"
        params = self._get_params()
        params['userId'] = user_id
        params['userSecret'] = user_secret

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            # SnapTrade usually returns { account: ..., positions: [...] } or similar.
            # Actually, /holdings returns a list of positions directly in some versions,
            # or inside a key. The docs say "List account holdings" returns a list.
            # Let's assume it returns the list directly or check response structure.
            # Standard SnapTrade response for holdings is the list of positions.
            return data.get('positions', []) if isinstance(data, dict) else data
        except requests.RequestException as e:
            print(f"SnapTrade Get Holdings Error: {e}")
            raise

    def normalize_holdings(self, snap_holdings: List[Dict], account_id: str, account_name: Optional[str] = None) -> List[Holding]:
        """
        Maps SnapTrade holdings to our normalized Holding model.
        """
        normalized = []
        for pos in snap_holdings:
            # Extract symbol data
            # SnapTrade position structure usually:
            # {
            #   "symbol": { "symbol": "AAPL", "description": "Apple", ... },
            #   "units": 10,
            #   "price": 150.0,
            #   "average_purchase_price": 140.0
            # }

            symbol_obj = pos.get("symbol", {})
            ticker = symbol_obj.get("symbol")

            # Skip if no ticker
            if not ticker:
                continue

            # Skip Options/Crypto if we only want Equities for now (per prompt)
            # Usually check security type. For now, we'll include everything that has a ticker.

            name = symbol_obj.get("description") or ticker
            qty = float(pos.get("units", 0) or 0)
            price = float(pos.get("price", 0) or 0)
            cost_basis = float(pos.get("average_purchase_price", 0) or 0)
            currency_obj = symbol_obj.get("currency", {})
            currency = currency_obj.get("code", "USD") if isinstance(currency_obj, dict) else "USD"

            # Attempt to determine institution if not provided
            institution = account_name if account_name else "SnapTrade"

            holding = Holding(
                symbol=ticker,
                name=name,
                quantity=qty,
                cost_basis=cost_basis,
                current_price=price,
                currency=currency,
                source="snaptrade",
                institution_name=institution,
                account_id=account_id,
                last_updated=datetime.now()
            )
            normalized.append(holding)

        return normalized

# Singleton instance
snaptrade_client = SnapTradeClient()
