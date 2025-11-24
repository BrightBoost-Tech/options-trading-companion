import os
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from dotenv import load_dotenv

# Force load .env
load_dotenv()

client_id = os.getenv("PLAID_CLIENT_ID")
secret = os.getenv("PLAID_SECRET")
env = os.getenv("PLAID_ENV", "sandbox")

print(f"Testing Credentials for: {env}")
print(f"Client ID: {client_id}")
print(f"Secret:    {'*' * 6 if secret else 'MISSING'}")

if not client_id or not secret:
    print("❌ KEYS MISSING. Check your .env file.")
    exit(1)

# Configure Plaid
configuration = plaid.Configuration(
    host=plaid.Environment.Sandbox,
    api_key={'clientId': client_id, 'secret': secret}
)
api_client = plaid.ApiClient(configuration)
client = plaid_api.PlaidApi(api_client)

try:
    request = LinkTokenCreateRequest(
        products=[Products.INVESTMENTS],
        client_name="Test Script",
        country_codes=[CountryCode.US],
        language='en',
        user=LinkTokenCreateRequestUser(client_user_id='test-user')
    )
    response = client.link_token_create(request)
    print("\n✅ SUCCESS! Real Token Generated:")
    print(f"Token: {response['link_token']}")
    print("(This proves your keys work. The issue is inside the main app's loading logic.)")
except Exception as e:
    print("\n❌ FAILED. Your keys are invalid or rejected by Plaid.")
    print(e)
