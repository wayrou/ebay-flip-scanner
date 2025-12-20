import os
import re
from typing import Optional, Tuple, List, Dict, Any

import yaml
import pandas as pd
from dotenv import load_dotenv

from ebay_oauth import EbayOAuth
from ebay_browse import browse_search
from rules import classify
from scoring import score_listing
from estimator import expected_profit
from alerts import discord_alert
from store import init_db, is_seen, mark_seen


def load_comps(path: str = "comps.csv") -> List[Dict[str, Any]]:
    df = pd.read_csv(path)
    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        rows.append(
            {
                "model": str(r["model"]),
                "working": float(r["working_resale"]),
                "asis": float(r["as_is_resale"]),
            }
        )
    return rows


def normalize_title(title: str) -> str:
    t = (title or "").lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def estimate_comps(title: str, comps_rows: List[Dict[str, Any]]) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    """
    Returns: (matched_model, working_resale, as_is_resale) or (None, None, None)
    Uses a simple "longest model substring wins" heuristic.
    """
    t = normalize_title(title)
    best = None
    best_len = 0

    for row in comps_rows:
        key = normalize_title(row["model"])
        if key and key in t and len(key) > best_len:
            best = row
            best_len = len(key)

    if not best:
        return None, None, None

    return best["model"], float(best["working"]), float(best["asis"])


def main() -> None:
    load_dotenv()

    cfg = yaml.safe_load(open("config.yaml", "r", encoding="utf-8"))

    webhook = os.getenv("DISCORD_WEBHOOK_URL", "")
    marketplace = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")

    max_price = float(cfg["thresholds"]["max_price"])
    min_score_alert = int(cfg["thresholds"]["min_score_alert"])
    min_expected_profit = float(cfg["thresholds"]["min_expected_profit"])
    topn = int(cfg["thresholds"]["max_results_print"])

    comps_rows = load_comps("comps.csv")

    con = init_db(cfg["db"]["path"])

    oauth = EbayOAuth()
    token = oauth.get_app_token()

    rows: List[Dict[str, Any]] = []

    for q in cfg["search"]["queries"]:
        data = browse_search(
            token=token,
            q=q,
            limit=cfg["search"]["limit_per_query"],
            marketplace_id=marketplace,
            buying_options=cfg["search"]["buying_options"],
        )

        for it in data.get("itemSummaries", []):
            item_id = it.get("itemId") or it.get("legacyItemId") or ""
            if not item_id:
                continue

            title = it.get("title", "")
            price = float((it.get("price") or {}).get("value", 0) or 0)
            if price <= 0 or price > max_price:
                continue

            # Prefer explicit shipping; fallback to default assumption
            ship = float(cfg["assumptions"]["shipping_cost_default"])
            shipping_options = it.get("shippingOptions") or []
            if shipping_options:
                ship_cost = (shipping_options[0] or {}).get("shippingCost", {}) or {}
                if ship_cost.get("value") is not None:
                    ship = float(ship_cost["value"])

            item_url = it.get("itemWebUrl", "")

            seller = it.get("seller", {}) or {}
            fb_pct_raw = seller.get("feedbackPercentage")
            fb_score_raw = seller.get("feedbackScore")

            fb_pct: Optional[float] = float(fb_pct_raw) if fb_pct_raw is not None else None
            fb_score: Optional[int] = int(fb_score_raw) if fb_score_raw is not None else None

            short_desc = it.get("shortDescription", "") or ""
            text_blob = f"{title}\n{short_desc}"

            bucket, _tags = classify(text_blob)

            matched_model, est_working, est_as_is = estimate_comps(title, comps_rows)

            score, why_list = score_listing(text_blob, fb_pct, fb_score, price, est_working)

            # P_fix by bucket
            if bucket == "GREEN":
                p_fix = float(cfg["assumptions"]["p_fix_green"])
            elif bucket == "YELLOW":
                p_fix = float(cfg["assumptions"]["p_fix_yellow"])
            else:
                p_fix = float(cfg["assumptions"]["p_fix_red"])

            exp: Optional[float] = None
            if est_working is not None and est_as_is is not None:
                exp = expected_profit(
                    buy=price,
                    ship=ship,
                    est_working=est_working,
                    est_as_is=est_as_is,
                    p_fix=p_fix,
                    fee_rate=float(cfg["assumptions"]["ebay_fee_rate"]),
                    parts_cost=float(cfg["assumptions"]["parts_cost_default"]),
                    time_cost=float(cfg["assumptions"]["time_cost_default"]),
                )

            rows.append(
                {
                    "query": q,
                    "bucket": bucket,
                    "score": score,
                    "expected_profit": exp,
                    "price": price,
                    "ship": ship,
                    "model_match": matched_model,
                    "title": title,
                    "url": item_url,
                    "why": "; ".join(why_list),
                    "item_id": item_id,
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        print("No results found.")
        return

    # Sort: GREEN first, then score descending
    bucket_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    df["bucket_rank"] = df["bucket"].map(bucket_order).fillna(9)
    df = df.sort_values(by=["bucket_rank", "score"], ascending=[True, False])

    # Print top results
    top = df.head(topn)
    print(top[["bucket", "score", "expected_profit", "price", "ship", "model_match", "title", "url", "why"]].to_string(index=False))

    # Discord alerts (deduped by SQLite)
    for _, r in df.iterrows():
        item_id = str(r["item_id"])

        if is_seen(con, item_id):
            continue

        score_ok = int(r["score"]) >= min_score_alert

        exp_val = r["expected_profit"]
        profit_ok = (pd.isna(exp_val)) or (float(exp_val) >= min_expected_profit)

        if score_ok and profit_ok and r["bucket"] in ("GREEN", "YELLOW"):
            msg = (
                f"🟢 GPU Deal Candidate\n"
                f"Bucket: {r['bucket']} | Score: {r['score']} | ExpProfit: {r['expected_profit']}\n"
                f"Price+Ship: ${float(r['price']):.2f}+${float(r['ship']):.2f}\n"
                f"ModelMatch: {r['model_match']}\n"
                f"{r['title']}\n"
                f"{r['url']}\n"
                f"Why: {r['why']}"
            )
            discord_alert(webhook, msg)

        mark_seen(con, item_id)


if __name__ == "__main__":
    main()