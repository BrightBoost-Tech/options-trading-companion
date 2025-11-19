import os
import plaid
from plaid.api import plaid_api
from plaid.model.investments_holdings_get_request import InvestmentsHoldingsGetRequest 
from plaid.model.country_code import CountryCode
from models import Holding
 
# Initialize Plaid Client
configuration = plaid.Configuration(
    host=plaid.Environment.Sandbox if os.getenv("PLAID_ENV") == "sandbox" else plaid.Environment.Development,
    api_key={
        'clientId': os.getenv("PLAID_CLIENT_ID"),
        'secret': os.getenv("PLAID_SECRET"),
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
 
        normalized_holdings = []
 
        for item in holdings_data:
            security_id = item.get('security_id')
            security = securities_data.get(security_id)
            
            # Skip if no ticker symbol (e.g., cash positions often lack symbols)
            if not security.get('ticker_symbol'):
                continue

            holding = Holding(
                symbol=security.get('ticker_symbol'),
                name=security.get('name'),
                quantity=float(item.get('quantity', 0)),
                cost_basis=float(item.get('cost_basis')) if item.get('cost_basis') is not None else None,
                current_price=float(security.get('close_price')) if security.get('close_price') is not None else float(item.get('institution_price')),
                currency=item.get('iso_currency_code')
            )
            normalized_holdings.append(holding)
            
        return normalized_holdings
 
    except plaid.ApiException as e:
        print(f"Plaid API Error: {e}")
        raise e
