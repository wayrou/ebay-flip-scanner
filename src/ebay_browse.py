import requests
from urllib.parse import urlencode

BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def browse_search(token: str, q: str, limit: int, marketplace_id: str, buying_options=None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }

    params = {"q": q, "limit": limit}
    if buying_options:
        params["filter"] = f"buyingOptions:{{{','.join(buying_options)}}}"

    url = f"{BROWSE_SEARCH_URL}?{urlencode(params)}"
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()