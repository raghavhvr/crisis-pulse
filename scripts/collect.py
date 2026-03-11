"""
Crisis Pulse — Multi-Source Data Collector
===========================================
Reads from public/signals_config.json (category + signal structure).
Writes:
  public/pulse_data.json    — rolling 7-day detail
  public/pulse_history.json — daily snapshot, appended + backfilled 30 days
"""

import os, json, time, logging, random, requests
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

MARKETS = {"AE": "UAE", "SA": "KSA", "KW": "Kuwait", "QA": "Qatar"}
SPORT_KW  = ["football","soccer","game","match","vs","ucl","league","cup","sport",
             "film","movie","music","cricket","ipl","nba","f1","basketball"]
CRISIS_KW = ["war","attack","crisis","shortage","price","inflation","ban",
             "sanction","protest","arrest","flood","earthquake","strike","conflict"]
BACKFILL_DAYS = 30

BASE_PATH    = Path(__file__).parent.parent
OUTPUT_PATH  = BASE_PATH / "public" / "pulse_data.json"
HISTORY_PATH = BASE_PATH / "public" / "pulse_history.json"
CONFIG_PATH  = BASE_PATH / "public" / "signals_config.json"


# ── Config loader ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        log.error(f"Cannot load signals_config.json: {e}")
        raise

def flat_signals(config: dict) -> dict:
    """Returns { signal_key: {label, wiki, news, guardian, category, ramadan_only} }"""
    out = {}
    now = datetime.now(timezone.utc).date()
    ramadan_active = config.get("ramadan_active", False)
    ramadan_end    = config.get("ramadan_end", "")
    if ramadan_end:
        try:
            ramadan_active = ramadan_active and now <= datetime.fromisoformat(ramadan_end).date()
        except:
            pass

    for cat_key, cat in config["categories"].items():
        if cat.get("ramadan_only") and not ramadan_active:
            log.info(f"  ⏭ Skipping Ramadan category (not active)")
            continue
        for sig_key, sig in cat["signals"].items():
            out[sig_key] = {**sig, "category": cat_key, "category_label": cat["label"],
                            "color": cat["color"], "icon": cat["icon"]}
    return out


# ── File helpers ──────────────────────────────────────────────────────────────

def safe_get(url, **kwargs):
    try:
        return requests.get(url, timeout=10, **kwargs)
    except Exception as e:
        log.warning(f"  Request failed: {e}")
        return None

def load_existing() -> dict:
    try:
        if OUTPUT_PATH.exists():
            d = json.loads(OUTPUT_PATH.read_text())
            if d.get("categories"):
                log.info(f"📂 Loaded previous data ({d.get('fetched_at','?')})")
                return d
    except Exception as e:
        log.warning(f"Could not load existing: {e}")
    return {}

def load_history() -> list:
    try:
        if HISTORY_PATH.exists():
            return json.loads(HISTORY_PATH.read_text())
    except: pass
    return []

def save_history(h: list):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(h, indent=2))


# ── Source 1: Google RSS ──────────────────────────────────────────────────────

def fetch_rss(geo: str) -> dict:
    r = safe_get(f"https://trends.google.com/trending/rss?geo={geo}",
                 headers={"User-Agent": "Mozilla/5.0"})
    if not r or r.status_code != 200:
        return {}
    try:
        root   = ET.fromstring(r.text)
        topics = [i.find("title").text or "" for i in root.findall(".//item") if i.find("title") is not None]
        total  = len(topics) or 1
        return {
            "sport_entertainment_pct": round(sum(1 for t in topics if any(k in t.lower() for k in SPORT_KW)) / total * 100),
            "crisis_pct":              round(sum(1 for t in topics if any(k in t.lower() for k in CRISIS_KW)) / total * 100),
            "top_topics":              topics[:10],
        }
    except Exception as e:
        log.warning(f"  RSS parse error [{geo}]: {e}")
        return {}


# ── Source 2: Wikipedia (range → dict) ───────────────────────────────────────

def fetch_wiki_range(article: str, start: str, end: str) -> dict:
    """Returns { 'YYYYMMDD': normalised_value }"""
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
           f"/en.wikipedia/all-access/user/{article}/daily/{start}/{end}")
    r = safe_get(url, headers={"User-Agent": "CrisisPulse/1.0"})
    if not r or r.status_code != 200:
        return {}
    items = r.json().get("items", [])
    if not items:
        return {}
    views = [i["views"] for i in items]
    max_v = max(views) or 1
    return {i["timestamp"][:8]: round(i["views"] / max_v * 100, 1) for i in items}

def fetch_wiki_list(article: str, start: str, end: str) -> list:
    d = fetch_wiki_range(article, start, end)
    return [d[k] for k in sorted(d.keys())] if d else []


# ── Source 3: NewsAPI ─────────────────────────────────────────────────────────

def fetch_newsapi(query: str, from_date: str, api_key: str) -> int:
    if not api_key: return 0
    r = safe_get("https://newsapi.org/v2/everything",
                 params={"q": query, "from": from_date, "language": "en", "pageSize": 1, "apiKey": api_key})
    return r.json().get("totalResults", 0) if r and r.status_code == 200 else 0


# ── Source 4: Guardian ────────────────────────────────────────────────────────

def fetch_guardian(query: str, from_date: str, api_key: str, to_date: str = "") -> int:
    if not api_key: return 0
    params = {"q": query, "from-date": from_date, "api-key": api_key, "page-size": 1}
    if to_date: params["to-date"] = to_date
    r = safe_get("https://content.guardianapis.com/search", params=params)
    return r.json().get("response", {}).get("total", 0) if r and r.status_code == 200 else 0


# ── Source 5: Twitch ──────────────────────────────────────────────────────────

def fetch_twitch(client_id: str, client_secret: str) -> dict:
    if not client_id or not client_secret: return {}
    try:
        t = requests.post("https://id.twitch.tv/oauth2/token",
                          data={"client_id": client_id, "client_secret": client_secret,
                                "grant_type": "client_credentials"}, timeout=10)
        if t.status_code != 200: return {}
        token   = t.json()["access_token"]
        s       = requests.get("https://api.twitch.tv/helix/streams", params={"first": 20},
                               headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"}, timeout=10)
        streams = s.json().get("data", []) if s.status_code == 200 else []
        games: dict[str, int] = {}
        for st in streams:
            g = st.get("game_name", "Unknown")
            games[g] = games.get(g, 0) + st["viewer_count"]
        top = sorted(games.items(), key=lambda x: x[1], reverse=True)[:5]
        return {"total_viewers": sum(st["viewer_count"] for st in streams),
                "top_games": [{"name": g, "viewers": v} for g, v in top]}
    except Exception as e:
        log.warning(f"  Twitch error: {e}")
        return {}


# ── Backfill ──────────────────────────────────────────────────────────────────

def backfill(signals: dict, guardian_key: str, newsapi_key: str) -> list:
    log.info(f"\n🔄 Backfilling {BACKFILL_DAYS} days...")
    now      = datetime.now(timezone.utc)
    start    = now - timedelta(days=BACKFILL_DAYS)
    start_s  = start.strftime("%Y%m%d00")
    end_s    = now.strftime("%Y%m%d00")

    # Wikipedia: one range call per signal
    wiki: dict[str, dict] = {}
    for sig_key, cfg in signals.items():
        time.sleep(0.3)
        d = fetch_wiki_range(cfg["wiki"], start_s, end_s)
        if d:
            wiki[sig_key] = d
            log.info(f"  ✓ Wiki {sig_key}: {len(d)} days")
        else:
            log.warning(f"  ✗ Wiki {sig_key}")

    # Guardian: weekly buckets → daily estimate
    guardian: dict[str, dict] = {}
    if guardian_key:
        for sig_key, cfg in signals.items():
            time.sleep(0.3)
            weekly: dict[str, int] = {}
            for w in range(5):
                w_start = (start + timedelta(weeks=w)).strftime("%Y-%m-%d")
                w_end   = (start + timedelta(weeks=w+1) - timedelta(days=1)).strftime("%Y-%m-%d")
                count   = fetch_guardian(cfg["guardian"], w_start, guardian_key, w_end)
                for d in range(7):
                    day = start + timedelta(weeks=w, days=d)
                    if day <= now:
                        weekly[day.strftime("%Y%m%d")] = round(count / 7)
            guardian[sig_key] = weekly
            log.info(f"  ✓ Guardian {sig_key}: {len(weekly)} day estimates")

    # NewsAPI: 30-day total → daily average
    newsapi: dict[str, int] = {}
    if newsapi_key:
        from_date = start.strftime("%Y-%m-%d")
        for sig_key, cfg in signals.items():
            time.sleep(0.3)
            total = fetch_newsapi(cfg["news"], from_date, newsapi_key)
            newsapi[sig_key] = round(total / BACKFILL_DAYS)

    # Assemble daily records
    records = []
    for days_ago in range(BACKFILL_DAYS, 0, -1):
        day     = now - timedelta(days=days_ago)
        day_str = day.strftime("%Y-%m-%d")
        day_key = day.strftime("%Y%m%d")

        record: dict = {"date": day_str, "markets": {}, "news_volumes": {}, "twitch_viewers": 0}

        for market_name in MARKETS.values():
            record["markets"][market_name] = {}
            for sig_key in signals:
                record["markets"][market_name][sig_key] = wiki.get(sig_key, {}).get(day_key)

        for sig_key in signals:
            g = guardian.get(sig_key, {}).get(day_key, 0)
            n = newsapi.get(sig_key, 0)
            record["news_volumes"][sig_key] = g + n

        records.append(record)

    log.info(f"✅ Backfill done — {len(records)} records")
    return records


# ── Today snapshot ────────────────────────────────────────────────────────────

def append_today(history: list, pulse: dict, signals: dict) -> list:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = [r for r in history if r.get("date") != today]  # replace if exists

    snap: dict = {
        "date": today, "markets": {}, "news_volumes": {},
        "twitch_viewers": pulse.get("global", {}).get("twitch", {}).get("total_viewers", 0),
    }
    for market_name in MARKETS.values():
        snap["markets"][market_name] = {
            sig_key: (vals[-1] if (vals := pulse.get("markets", {}).get(market_name, {}).get(sig_key, [])) else None)
            for sig_key in signals
        }
    for sig_key in signals:
        na = pulse.get("news_volumes", {}).get("newsapi",  {}).get(sig_key, 0)
        gd = pulse.get("news_volumes", {}).get("guardian", {}).get(sig_key, 0)
        snap["news_volumes"][sig_key] = na + gd

    history.append(snap)
    log.info(f"📅 Appended {today}. Total: {len(history)} records")
    return history


# ── Main ──────────────────────────────────────────────────────────────────────

def collect():
    newsapi_key   = os.getenv("NEWSAPI_KEY", "")
    guardian_key  = os.getenv("GUARDIAN_KEY", "")
    twitch_id     = os.getenv("TWITCH_CLIENT_ID", "")
    twitch_secret = os.getenv("TWITCH_CLIENT_SECRET", "")

    config  = load_config()
    signals = flat_signals(config)
    log.info(f"📋 {len(signals)} active signals across {len(config['categories'])} categories")

    existing = load_existing()
    history  = load_history()
    now      = datetime.now(timezone.utc)
    end_dt   = now.strftime("%Y%m%d00")
    start_dt = (now - timedelta(days=8)).strftime("%Y%m%d00")
    from_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    date_labels = [(now - timedelta(days=7-i)).strftime("%b %d") for i in range(8)]

    # Check if backfill needed
    existing_dates = {r["date"] for r in history}
    missing = [
        (now - timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(BACKFILL_DAYS, 0, -1)
        if (now - timedelta(days=d)).strftime("%Y-%m-%d") not in existing_dates
    ]
    if missing:
        log.info(f"📭 History missing {len(missing)} days — running backfill")
        backfilled = backfill(signals, guardian_key, newsapi_key)
        # Merge: keep existing records, add backfilled ones for missing dates
        bf_by_date = {r["date"]: r for r in backfilled}
        history = [r for r in history if r["date"] not in bf_by_date]
        history = sorted(history + list(bf_by_date.values()), key=lambda r: r["date"])
        save_history(history)
        log.info(f"✅ History now has {len(history)} records after backfill")
    else:
        log.info(f"✅ History complete — {len(history)} records, no backfill needed")

    # Build result structure mirroring category hierarchy
    result = {
        "fetched_at":     now.isoformat(),
        "dates":          date_labels,
        "categories":     {},
        "markets":        {},
        "global":         {},
        "news_volumes":   {},
        "sources_live":   [],
        "sources_failed": [],
        "ramadan_active": config.get("ramadan_active", False),
    }

    # Pre-fill markets from existing
    for market_name in MARKETS.values():
        result["markets"][market_name] = dict(existing.get("markets", {}).get(market_name, {}))

    # Build category metadata for dashboard
    for cat_key, cat in config["categories"].items():
        result["categories"][cat_key] = {
            "label": cat["label"], "icon": cat["icon"],
            "color": cat["color"], "hypothesis": cat.get("hypothesis", ""),
            "ramadan_only": cat.get("ramadan_only", False),
            "signals": list(cat["signals"].keys()),
        }

    # ── Wikipedia ────────────────────────────────────────────────────────────
    log.info("\n📖 Wikipedia Pageviews...")
    wiki_data = {}
    for sig_key, cfg in signals.items():
        time.sleep(0.4)
        values = fetch_wiki_list(cfg["wiki"], start_dt, end_dt)
        if values:
            wiki_data[sig_key] = values
            log.info(f"  ✓ {sig_key}: {values[-1]}")
        else:
            log.warning(f"  ✗ {sig_key}")

    if wiki_data:
        result["global"]["wikipedia"] = wiki_data
        result["sources_live"].append("wikipedia")
        for market_name in MARKETS.values():
            for sig_key, values in wiki_data.items():
                if not result["markets"][market_name].get(sig_key):
                    result["markets"][market_name][sig_key] = values
    else:
        result["sources_failed"].append("wikipedia")

    # ── Google RSS ───────────────────────────────────────────────────────────
    log.info("\n📡 Google RSS Trends...")
    rss_data = {}
    for geo, market_name in MARKETS.items():
        time.sleep(random.uniform(1, 2))
        trends = fetch_rss(geo)
        if trends:
            rss_data[market_name] = trends
            log.info(f"  ✓ {market_name}: sport={trends['sport_entertainment_pct']}% crisis={trends['crisis_pct']}%")
        else:
            log.warning(f"  ✗ {market_name}")

    if rss_data:
        result["global"]["rss_trends"] = rss_data
        result["sources_live"].append("google_rss")
    else:
        result["sources_failed"].append("google_rss")

    # ── NewsAPI ──────────────────────────────────────────────────────────────
    log.info("\n📰 NewsAPI...")
    if newsapi_key:
        news_vols = {}
        for sig_key, cfg in signals.items():
            time.sleep(0.4)
            count = fetch_newsapi(cfg["news"], from_date, newsapi_key)
            news_vols[sig_key] = count
            log.info(f"  ✓ {sig_key}: {count}")
        result["news_volumes"]["newsapi"] = news_vols
        result["sources_live"].append("newsapi")
    else:
        log.warning("  ✗ NEWSAPI_KEY not set")
        result["sources_failed"].append("newsapi")

    # ── Guardian ─────────────────────────────────────────────────────────────
    log.info("\n🔵 Guardian...")
    if guardian_key:
        gd_vols = {}
        for sig_key, cfg in signals.items():
            time.sleep(0.4)
            count = fetch_guardian(cfg["guardian"], from_date, guardian_key)
            gd_vols[sig_key] = count
            log.info(f"  ✓ {sig_key}: {count}")
        result["news_volumes"]["guardian"] = gd_vols
        result["sources_live"].append("guardian")
    else:
        log.warning("  ✗ GUARDIAN_KEY not set")
        result["sources_failed"].append("guardian")

    # ── Twitch ───────────────────────────────────────────────────────────────
    log.info("\n🎮 Twitch...")
    if twitch_id and twitch_secret:
        twitch_data = fetch_twitch(twitch_id, twitch_secret)
        if twitch_data:
            result["global"]["twitch"] = twitch_data
            result["sources_live"].append("twitch")
            log.info(f"  ✓ {twitch_data['total_viewers']:,} viewers")
        else:
            result["sources_failed"].append("twitch")
    else:
        log.warning("  ✗ Twitch credentials not set")
        result["sources_failed"].append("twitch")

    log.info(f"\n✅ Live: {result['sources_live']}")
    if result["sources_failed"]:
        log.info(f"   Failed: {result['sources_failed']}")

    return result, signals, config


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("  Crisis Pulse — Multi-Source Collector")
    log.info(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 50)

    try:
        data, signals, config = collect()
    except Exception as e:
        log.error(f"Collection failed: {e}")
        existing = load_existing()
        if existing:
            existing["fetched_at"] = datetime.now(timezone.utc).isoformat()
            existing["error"] = str(e)
            data, signals, config = existing, {}, {}
        else:
            raise

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2))
    log.info(f"📄 pulse_data.json written")

    if signals:
        history = load_history()
        history = append_today(history, data, signals)
        save_history(history)
        log.info(f"📅 pulse_history.json written")