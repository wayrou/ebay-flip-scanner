import base64
import os
import time
import requests


TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"


class EbayOAuth:
    def __init__(self):
        self.client_id = os.getenv("EBAY_CLIENT_ID")
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET")
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET. Set them in .env or your environment."
            )
        self._token = None
        self._exp = 0

    def get_app_token(self, scope: str = "https://api.ebay.com/oauth/api_scope") -> str:
        now = int(time.time())
        if self._token and now < self._exp - 60:
            return self._token

        creds = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        b64 = base64.b64encode(creds).decode("utf-8")

        headers = {
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials", "scope": scope}

        r = requests.post(TOKEN_URL, headers=headers, data=data, timeout=30)
        try:
            r.raise_for_status()
        except requests.HTTPError as exc:
            body = r.text.strip()
            if body:
                raise requests.HTTPError(f"{exc} | eBay token response: {body[:500]}") from exc
            raise
        payload = r.json()

        self._token = payload["access_token"]
        self._exp = now + int(payload.get("expires_in", 7200))
        return self._token
