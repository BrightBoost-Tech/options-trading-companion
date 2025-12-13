from pydantic import BaseModel
from typing import Optional
import os

class PlaidSecrets(BaseModel):
    client_id: Optional[str]
    secret: Optional[str]
    env: str  # 'sandbox' | 'development' | 'production'

class SupabaseSecrets(BaseModel):
    url: Optional[str]
    service_role_key: Optional[str]
    anon_key: Optional[str]
    jwt_secret: Optional[str]

class PolygonSecrets(BaseModel):
    api_key: Optional[str]

class QciSecrets(BaseModel):
    api_token: Optional[str]

class SecretsProvider:
    """
    Central access point for backend-wide secrets.
    """
    def __init__(self):
        self._plaid: Optional[PlaidSecrets] = None
        self._supabase: Optional[SupabaseSecrets] = None
        self._polygon: Optional[PolygonSecrets] = None
        self._qci: Optional[QciSecrets] = None

    def get_plaid_secrets(self) -> PlaidSecrets:
        if self._plaid is None:
            self._plaid = PlaidSecrets(
                client_id=os.getenv("PLAID_CLIENT_ID"),
                secret=os.getenv("PLAID_SECRET"),
                env=os.getenv("PLAID_ENV", "sandbox"),
            )
        return self._plaid

    def get_supabase_secrets(self) -> SupabaseSecrets:
        if self._supabase is None:
            self._supabase = SupabaseSecrets(
                url=os.getenv("NEXT_PUBLIC_SUPABASE_URL"),
                service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
                anon_key=os.getenv("SUPABASE_ANON_KEY"),
                jwt_secret=os.getenv("SUPABASE_JWT_SECRET"),
            )
        return self._supabase

    def get_polygon_secrets(self) -> PolygonSecrets:
        if self._polygon is None:
            self._polygon = PolygonSecrets(api_key=os.getenv("POLYGON_API_KEY"))
        return self._polygon

    def get_qci_secrets(self) -> QciSecrets:
        if self._qci is None:
            self._qci = QciSecrets(api_token=os.getenv("QCI_API_TOKEN"))
        return self._qci
