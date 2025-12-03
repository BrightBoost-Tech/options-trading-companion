import pytest
import os
from unittest.mock import MagicMock, patch
from security.secrets_provider import SecretsProvider
from services.token_store import PlaidTokenStore

# In SecretsProvider, get_supabase_secrets looks for NEXT_PUBLIC_SUPABASE_URL, not SUPABASE_URL.
# It seems weird for backend to use NEXT_PUBLIC prefix, but that's what the code says.

@patch.dict(os.environ, {
    "PLAID_CLIENT_ID": "test_client",
    "PLAID_SECRET": "test_secret",
    "NEXT_PUBLIC_SUPABASE_URL": "http://supa.test",
    "SUPABASE_SERVICE_ROLE_KEY": "supa_key",
    "POLYGON_API_KEY": "poly_key",
    "QCI_API_TOKEN": "qci_token"
})
def test_secrets_provider():
    # We instantiate provider inside the patch context
    provider = SecretsProvider()

    plaid = provider.get_plaid_secrets()
    assert plaid.client_id == "test_client"
    assert plaid.secret == "test_secret"

    supa = provider.get_supabase_secrets()
    # It reads NEXT_PUBLIC_SUPABASE_URL
    assert supa.url == "http://supa.test"

    assert provider.get_polygon_secrets().api_key == "poly_key"
    assert provider.get_qci_secrets().api_token == "qci_token"

def test_plaid_token_store_get():
    mock_supabase = MagicMock()
    store = PlaidTokenStore(mock_supabase)

    # Mock user_settings success
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "plaid_access_token": "gAAAAAB..." # Encrypted
    }

    # Mock decryption
    with patch("services.token_store.decrypt_token", return_value="access-sandbox-123"):
        token = store.get_access_token("user1")
        assert token == "access-sandbox-123"

def test_plaid_token_store_fallback():
    mock_supabase = MagicMock()
    store = PlaidTokenStore(mock_supabase)

    # Mock user_settings empty
    mock_supabase.table("user_settings").select().eq().single().execute().data = None

    # Mock plaid_items fallback
    mock_supabase.table("plaid_items").select().eq().limit().execute().data = [
        {"access_token": "gAAAAAB..."}
    ]

    with patch("services.token_store.decrypt_token", return_value="fallback-token"):
        token = store.get_access_token("user1")
        assert token == "fallback-token"

def test_plaid_token_store_save():
    mock_supabase = MagicMock()
    store = PlaidTokenStore(mock_supabase)

    with patch("services.token_store.encrypt_token", return_value="gAAAAAB..."):
        # Fix: Pass dictionary with item_id for metadata
        store.save_access_token("user1", "new-token", {"item_id": "item1"})

        # Verify upserts to both tables
        assert mock_supabase.table("user_settings").upsert.called
        assert mock_supabase.table("plaid_items").upsert.called
