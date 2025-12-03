from typing import Optional, Dict
from supabase import Client
from security import encrypt_token, decrypt_token

class PlaidTokenStore:
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def get_access_token(self, user_id: str) -> Optional[str]:
        """
        1. Check user_settings.plaid_access_token
        2. Fallback to plaid_items.access_token
        3. Decrypt using decrypt_token when stored encrypted.
        Returns plaintext access token or None.
        """
        if not self.supabase:
            return None

        # 1. Check user_settings first (preferred)
        try:
            res = (
                self.supabase.table("user_settings")
                .select("plaid_access_token")
                .eq("user_id", user_id)
                .single()
                .execute()
            )
            if res.data:
                raw_token = res.data.get("plaid_access_token")
                if raw_token:
                    try:
                        return decrypt_token(raw_token)
                    except Exception:
                        # Fallback to raw if decryption fails (e.g. migration or old plain text)
                        return raw_token
        except Exception:
            pass

        # 2. Fallback to plaid_items if not in user_settings
        try:
            response = (
                self.supabase.table("plaid_items")
                .select("access_token")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if response.data:
                raw_token = response.data[0].get("access_token")
                if raw_token:
                    try:
                        return decrypt_token(raw_token)
                    except Exception:
                        return raw_token
        except Exception:
            pass

        return None

    def save_access_token(self, user_id: str, access_token: str, metadata: Dict) -> None:
        """
        Encrypts the access token and upserts both:
          - user_settings (single primary connection)
          - plaid_items (supports multiple items per user)
        """
        if not self.supabase or not user_id or not access_token:
            return

        item_id = metadata.get('item_id')
        institution_name = "Plaid Item"
        institution_id = None
        if metadata and 'institution' in metadata:
            institution_name = metadata['institution'].get('name', 'Plaid Item')
            institution_id = metadata['institution'].get('institution_id')

        # Encrypt token before saving
        encrypted_access_token = encrypt_token(access_token)

        # 1. Update user_settings
        try:
            self.supabase.table("user_settings").upsert({
                "user_id": user_id,
                "plaid_access_token": encrypted_access_token,
                "plaid_item_id": item_id,
                "plaid_institution": institution_name,
                "updated_at": "now()"
            }, on_conflict="user_id").execute()
            print(f"✅ User Settings updated with Plaid credentials for user {user_id}")
        except Exception as e:
            print(f"⚠️ Failed to update user_settings: {e}")

        # 2. Update plaid_items
        try:
            self.supabase.table("plaid_items").upsert({
                "user_id": user_id,
                "access_token": encrypted_access_token,
                "item_id": item_id,
                "institution_name": institution_name,
                "institution_id": institution_id,
                "status": "active",
                "updated_at": "now()"
            }, on_conflict="user_id").execute()
            print("✅ Plaid Item Saved to DB")
        except Exception as e:
             print(f"❌ Failed to save Plaid Item to DB: {e}")
