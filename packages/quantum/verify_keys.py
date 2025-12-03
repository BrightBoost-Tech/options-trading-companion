import os
import plaid
import sys
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from dotenv import load_dotenv

# Allow importing from local package
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Explicitly load .env for standalone script usage
load_dotenv()

from security.secrets_provider import SecretsProvider

secrets_provider = SecretsProvider()
plaid_secrets = secrets_provider.get_plaid_secrets()

client_id = plaid_secrets.client_id
secret = plaid_secrets.secret
env = plaid_secrets.env

print(f"Testing Credentials for: {env}")
print(f"Client ID: {client_id}")
print(f"Secret:    {'*' * 6 if secret else 'MISSING'}")

if not client_id or not secret:
    print("❌ KEYS MISSING. Check your .env file or environment.")
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
        products=[Products('investments')],
        client_name="Test Script",
        country_codes=[CountryCode('US')],
        language='en',
        user=LinkTokenCreateRequestUser(client_user_id='test-user')
    )
    response = client.link_token_create(request)
    print("\n✅ SUCCESS! Real Token Generated:")
    print(f"Token: {response['link_token']}")
    print("(This proves your keys work and SecretsProvider is correctly reading env.)")
except Exception as e:
    print("\n❌ FAILED. Your keys are invalid or rejected by Plaid.")
    print(e)
