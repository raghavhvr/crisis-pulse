"""
Crisis Pulse — Multi-Source Data Collector
===========================================
Sources:
  1. Google Trends RSS   — trending topic signals per market (no auth)
  2. Wikipedia Pageviews — behavioral interest index per signal (no auth)
  3. NewsAPI             — global news article volume per signal keyword
  4. Guardian API        — global news article volume per signal keyword
  5. Twitch API          — live global gaming viewership

Reads API keys from .env locally, GitHub Secrets in Actions.
On any partial failure, preserves previous pull for that signal.
"""

import os, json, time, logging, random, requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

MARKETS = {"AE": "UAE", "SA": "KSA", "KW": "Kuwait", "QA": "Qatar"}

SIGNALS = {
    "gaming":   {"wiki": "Gaming",       "news": "gaming esports",          "guardian": "gaming"},
    "wellness": {"wiki": "Wellness",      "news": "mental health wellness",  "guardian": "mental health"},
    "news":     {"wiki": "News_media",    "news": "breaking news",           "guardian": "world"},
    "cheap":    {"wiki": "Inflation",     "news": "inflation prices cost",   "guardian": "inflation"},
    "delivery": {"wiki": "Food_delivery", "news": "food delivery logistics", "guardian": "delivery"},
}

SPORT_KW  = ["football","soccer","game","match","vs","ucl","league","cup","sport",
             "film","movie","music","cricket","ipl","nba","f1","basketball"]
CRISIS_KW = ["war","attack","crisis","shortage","price","inflation","ban",
             "sanction","protest","arrest","flood","earthquake","strike","conflict"]

OUTPUT_PATH = Path(__file__).parent.parent / "public" / "pulse_data.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_get(url, **kwargs):
    try:
        return requests.get(url, timeout=10, **kwargs)
    except Exception as e:
        log.warning(f"  Request failed: {e}")
        return None


def load_existing() -> dict:
    try:
        if OUTPUT_PATH.exists():
            data = json.loads(OUTPUT_PATH.read_text())
            if data.get("markets") and data.get("fetched_at") != "fallback":
                log.info(f"📂 Loaded previous data ({data.get('fetched_at','?')})")
                return data
    except Exception as e:
        log.warning(f"Could not load existing: {e}")
    return {}


# ── Source 1: Google RSS Trends ───────────────────────────────────────────────

def fetch_rss_trends(geo: str) -> dict:
    r = safe_get(f"https://trends.google.com/trending/rss?geo={geo}",
                 headers={"User-Agent": "Mozilla/5.0"})
    if not r or r.status_code != 200:
        return {}
    try:
        root   = ET.fromstring(r.text)
        topics = [item.find("title").text or ""
                  for item in root.findall(".//item")
                  if item.find("title") is not None]
        total  = len(topics) or 1
        sport  = sum(1 for t in topics if any(k in t.lower() for k in SPORT_KW))
        crisis = sum(1 for t in topics if any(k in t.lower() for k in CRISIS_KW))
        return {
            "sport_entertainment_pct": round(sport  / total * 100),
            "crisis_pct":              round(crisis / total * 100),
            "top_topics":              topics[:10],
        }
    except Exception as e:
        log.warning(f"  RSS parse error [{geo}]: {e}")
        return {}


# ── Source 2: Wikipedia Pageviews ─────────────────────────────────────────────

def fetch_wiki_pageviews(article: str, start: str, end: str) -> list:
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
           f"/en.wikipedia/all-access/user/{article}/daily/{start}/{end}")
    r = safe_get(url, headers={"User-Agent": "CrisisPulse/1.0 (github.com/raghavhvr/crisis-pulse)"})
    if not r or r.status_code != 200:
        return []
    items = r.json().get("items", [])
    if not items:
        return []
    views = [i["views"] for i in items]
    max_v = max(views) or 1
    return [round(v / max_v * 100, 1) for v in views]


# ── Source 3: NewsAPI ─────────────────────────────────────────────────────────

def fetch_newsapi_volume(query: str, from_date: str, api_key: str) -> int:
    if not api_key:
        return 0
    r = safe_get("https://newsapi.org/v2/everything", params={
        "q": query, "from": from_date, "language": "en",
        "pageSize": 1, "apiKey": api_key,
    })
    if not r or r.status_code != 200:
        log.warning(f"  NewsAPI {r.status_code if r else 'timeout'}: {r.json().get('message','') if r else ''}")
        return 0
    return r.json().get("totalResults", 0)


# ── Source 4: Guardian API ────────────────────────────────────────────────────

def fetch_guardian_volume(query: str, from_date: str, api_key: str) -> int:
    if not api_key:
        return 0
    r = safe_get("https://content.guardianapis.com/search", params={
        "q": query, "from-date": from_date,
        "api-key": api_key, "page-size": 1,
    })
    if not r or r.status_code != 200:
        log.warning(f"  Guardian {r.status_code if r else 'timeout'}")
        return 0
    return r.json().get("response", {}).get("total", 0)


# ── Source 5: Twitch ──────────────────────────────────────────────────────────

def fetch_twitch_gaming(client_id: str, client_secret: str) -> dict:
    if not client_id or not client_secret:
        return {}
    try:
        token_r = requests.post("https://id.twitch.tv/oauth2/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "grant_type": "client_credentials",
        }, timeout=10)
        if token_r.status_code != 200:
            log.warning(f"  Twitch auth failed: {token_r.status_code}")
            return {}
        token   = token_r.json()["access_token"]
        s_r     = requests.get("https://api.twitch.tv/helix/streams", params={"first": 20},
                      headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"},
                      timeout=10)
        streams = s_r.json().get("data", []) if s_r.status_code == 200 else []
        games   = {}
        for s in streams:
            g = s.get("game_name", "Unknown")
            games[g] = games.get(g, 0) + s["viewer_count"]
        top = sorted(games.items(), key=lambda x: x[1], reverse=True)[:5]
        return {
            "total_viewers": sum(s["viewer_count"] for s in streams),
            "top_games": [{"name": g, "viewers": v} for g, v in top],
        }
    except Exception as e:
        log.warning(f"  Twitch error: {e}")
        return {}


# ── Main Collector ────────────────────────────────────────────────────────────

def collect() -> dict:
    newsapi_key   = os.getenv("NEWSAPI_KEY",       "")
    guardian_key  = os.getenv("GUARDIAN_KEY",      "")
    twitch_id     = os.getenv("TWITCH_CLIENT_ID",  "")
    twitch_secret = os.getenv("TWITCH_CLIENT_SECRET", "")

    existing = load_existing()
    now      = datetime.now(timezone.utc)
    end_dt   = now.strftime("%Y%m%d00")
    start_dt = (now - timedelta(days=8)).strftime("%Y%m%d00")
    from_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    date_labels = [(now - timedelta(days=7-i)).strftime("%b %d") for i in range(8)]

    result = {
        "fetched_at":     now.isoformat(),
        "dates":          date_labels,
        "markets":        {},
        "global":         {},
        "news_volumes":   {},
        "sources_live":   [],
        "sources_failed": [],
    }

    # Pre-fill all markets from previous pull as fallback baseline
    for market_name in MARKETS.values():
        result["markets"][market_name] = dict(
            existing.get("markets", {}).get(market_name, {})
        )

    # ── Wikipedia ────────────────────────────────────────────────────────────
    log.info("📖 Wikipedia Pageviews...")
    wiki_data = {}
    for signal_key, cfg in SIGNALS.items():
        time.sleep(0.5)
        values = fetch_wiki_pageviews(cfg["wiki"], start_dt, end_dt)
        if values:
            wiki_data[signal_key] = values
            log.info(f"  ✓ {signal_key}: {values[-1]} (latest)")
        else:
            log.warning(f"  ✗ {signal_key}: no data")

    if wiki_data:
        result["global"]["wikipedia"] = wiki_data
        result["sources_live"].append("wikipedia")
        # Use as market signal baseline where no existing data exists
        for market_name in MARKETS.values():
            for signal_key, values in wiki_data.items():
                if not result["markets"][market_name].get(signal_key):
                    result["markets"][market_name][signal_key] = values
    else:
        result["sources_failed"].append("wikipedia")

    # ── Google RSS ───────────────────────────────────────────────────────────
    log.info("\n📡 Google RSS Trends...")
    rss_data = {}
    for geo, market_name in MARKETS.items():
        time.sleep(random.uniform(1, 2))
        trends = fetch_rss_trends(geo)
        if trends:
            rss_data[market_name] = trends
            log.info(f"  ✓ {market_name}: sport={trends['sport_entertainment_pct']}% crisis={trends['crisis_pct']}%")
        else:
            log.warning(f"  ✗ {market_name}: failed")

    if rss_data:
        result["global"]["rss_trends"] = rss_data
        result["sources_live"].append("google_rss")
    else:
        result["sources_failed"].append("google_rss")

    # ── NewsAPI ──────────────────────────────────────────────────────────────
    log.info("\n📰 NewsAPI...")
    if newsapi_key:
        news_vols = {}
        for signal_key, cfg in SIGNALS.items():
            time.sleep(0.5)
            count = fetch_newsapi_volume(cfg["news"], from_date, newsapi_key)
            news_vols[signal_key] = count
            log.info(f"  ✓ {signal_key}: {count} articles")
        result["news_volumes"]["newsapi"] = news_vols
        result["sources_live"].append("newsapi")
    else:
        log.warning("  ✗ NEWSAPI_KEY not set")
        result["sources_failed"].append("newsapi")

    # ── Guardian ─────────────────────────────────────────────────────────────
    log.info("\n🔵 Guardian API...")
    if guardian_key:
        guardian_vols = {}
        for signal_key, cfg in SIGNALS.items():
            time.sleep(0.5)
            count = fetch_guardian_volume(cfg["guardian"], from_date, guardian_key)
            guardian_vols[signal_key] = count
            log.info(f"  ✓ {signal_key}: {count} articles")
        result["news_volumes"]["guardian"] = guardian_vols
        result["sources_live"].append("guardian")
    else:
        log.warning("  ✗ GUARDIAN_KEY not set")
        result["sources_failed"].append("guardian")

    # ── Twitch ───────────────────────────────────────────────────────────────
    log.info("\n🎮 Twitch...")
    if twitch_id and twitch_secret:
        twitch_data = fetch_twitch_gaming(twitch_id, twitch_secret)
        if twitch_data:
            result["global"]["twitch"] = twitch_data
            result["sources_live"].append("twitch")
            log.info(f"  ✓ {twitch_data['total_viewers']:,} total viewers")
            for g in twitch_data["top_games"]:
                log.info(f"    {g['name']}: {g['viewers']:,}")
        else:
            result["sources_failed"].append("twitch")
    else:
        log.warning("  ✗ Twitch credentials not set")
        result["sources_failed"].append("twitch")

    log.info(f"\n✅ Live: {result['sources_live']}")
    if result["sources_failed"]:
        log.info(f"   Failed: {result['sources_failed']}")
    return result


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  Crisis Pulse — Multi-Source Collector")
    log.info(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 50)

    try:
        data = collect()
    except Exception as e:
        log.error(f"Collection failed: {e}")
        existing = load_existing()
        if existing:
            existing["fetched_at"] = datetime.now(timezone.utc).isoformat()
            existing["error"] = str(e)
            data = existing
            log.info("Kept existing data with updated timestamp")
        else:
            raise

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2))
    log.info(f"📄 Written → {OUTPUT_PATH}")