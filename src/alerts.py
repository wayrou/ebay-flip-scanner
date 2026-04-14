import requests


def discord_alert(webhook_url: str, content: str):
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL is not set.")

    response = requests.post(webhook_url, json={"content": content}, timeout=20)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text.strip()
        if body:
            raise requests.HTTPError(f"{exc} | Discord response: {body[:500]}") from exc
        raise
