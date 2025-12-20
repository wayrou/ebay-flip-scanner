import requests

def discord_alert(webhook_url: str, content: str):
    if not webhook_url:
        return
    r = requests.post(webhook_url, json={"content": content}, timeout=20)
    r.raise_for_status()