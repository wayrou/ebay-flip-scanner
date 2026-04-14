import requests
from urllib.parse import urlencode

BROWSE_SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"


def browse_search(
    token: str,
    q: str,
    limit: int,
    marketplace_id: str,
    buying_options=None,
    category_ids=None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
    }

    params = {"q": q, "limit": limit}
    if category_ids:
        params["category_ids"] = ",".join(str(category_id) for category_id in category_ids)

    filters = []
    if buying_options:
        filters.append(f"buyingOptions:{{{'|'.join(buying_options)}}}")
    if filters:
        params["filter"] = ",".join(filters)

    url = f"{BROWSE_SEARCH_URL}?{urlencode(params)}"
    r = requests.get(url, headers=headers, timeout=30)
    try:
        r.raise_for_status()
    except requests.HTTPError as exc:
        body = r.text.strip()
        if body:
            raise requests.HTTPError(f"{exc} | eBay response: {body[:500]}") from exc
        raise
    return r.json()
