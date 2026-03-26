import pytest
import os
from unittest.mock import MagicMock, patch
from packages.quantum.security.secrets_provider import SecretsProvider


@patch.dict(os.environ, {
    "NEXT_PUBLIC_SUPABASE_URL": "http://supa.test",
    "SUPABASE_SERVICE_ROLE_KEY": "supa_key",
    "POLYGON_API_KEY": "poly_key",
    "QCI_API_TOKEN": "qci_token"
})
def test_secrets_provider():
    provider = SecretsProvider()

    supa = provider.get_supabase_secrets()
    assert supa.url == "http://supa.test"

    assert provider.get_polygon_secrets().api_key == "poly_key"
    assert provider.get_qci_secrets().api_token == "qci_token"
