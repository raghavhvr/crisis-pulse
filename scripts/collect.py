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

# NewsAPI geo-filter terms per market
MARKET_NEWS_TERMS = {
    "UAE":    "UAE OR Dubai OR Abu Dhabi OR Emirates",
    "KSA":    "Saudi Arabia OR Riyadh OR Jeddah OR KSA",
    "Kuwait": "Kuwait",
    "Qatar":  "Qatar OR Doha",
}
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

def fetch_newsapi(query: str, from_date: str, api_key: str, market: str = "") -> int:
    if not api_key: return 0
    geo = MARKET_NEWS_TERMS.get(market, "")
    full_query = f"({query}) AND ({geo})" if geo else query
    r = safe_get("https://newsapi.org/v2/everything",
                 params={"q": full_query, "from": from_date, "language": "en", "pageSize": 1, "apiKey": api_key})
    if r and r.status_code == 200:
        return r.json().get("totalResults", 0)
    log.warning(f"  NewsAPI error {r.status_code if r else 'timeout'} [{market or 'global'}]")
    return 0


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

    # NewsAPI: single batched query per market for the full period
    newsapi: dict[str, dict] = {m: {} for m in MARKETS.values()}
    if newsapi_key:
        from_date = start.strftime("%Y-%m-%d")
        for market_name in MARKETS.values():
            geo = MARKET_NEWS_TERMS.get(market_name, market_name)
            r = safe_get("https://newsapi.org/v2/everything",
                         params={"q": geo, "from": from_date, "language": "en",
                                 "pageSize": 1, "apiKey": newsapi_key})
            total = r.json().get("totalResults", 0) if r and r.status_code == 200 else 0
            per_sig_per_day = max(1, round(total / len(signals) / BACKFILL_DAYS))
            for sig_key in signals:
                newsapi[market_name][sig_key] = per_sig_per_day
            time.sleep(0.5)

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
            # Average across markets for history record
            n_vals = [newsapi.get(m, {}).get(sig_key, 0) for m in MARKETS.values()]
            n = round(sum(n_vals) / len(n_vals)) if n_vals else 0
            record["news_volumes"][sig_key] = g + n

        records.append(record)

    log.info(f"✅ Backfill done — {len(records)} records")
    return records


# ── Today snapshot ────────────────────────────────────────────────────────────

def append_today(history: list, pulse: dict, signals: dict) -> list:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    history = [r for r in history if r.get("date") != today]  # replace if exists

    newsapi_raw = pulse.get("news_volumes", {}).get("newsapi", {})
    guardian    = pulse.get("news_volumes", {}).get("guardian", {})
    is_per_market = isinstance(next(iter(newsapi_raw.values()), None), dict)

    snap: dict = {
        "date": today,
        "markets": {},
        "news_volumes": {},        # flat global rollup (backwards compat)
        "news_volumes_by_market": {},  # NEW: per-market news volumes
        "twitch_viewers": pulse.get("global", {}).get("twitch", {}).get("total_viewers", 0),
    }

    # Per-market scores: blend wiki (last value) + per-market newsapi normalised
    all_market_totals = {}
    for market_name in MARKETS.values():
        mkt_news = newsapi_raw.get(market_name, {}) if is_per_market else {}
        all_market_totals[market_name] = sum(mkt_news.get(s, 0) for s in signals)

    max_total = max(all_market_totals.values(), default=1) or 1

    for market_name in MARKETS.values():
        wiki_vals = {}
        for sig_key in signals:
            raw = pulse.get("markets", {}).get(market_name, {}).get(sig_key, [])
            wiki_vals[sig_key] = raw[-1] if raw else None

        mkt_news = newsapi_raw.get(market_name, {}) if is_per_market else {}
        mkt_total = all_market_totals.get(market_name, 0)
        # Normalise this market's news volume relative to the highest-volume market
        mkt_news_factor = mkt_total / max_total  # 0.0 – 1.0

        snap["markets"][market_name] = {}
        snap["news_volumes_by_market"][market_name] = {}
        for sig_key in signals:
            wiki = wiki_vals.get(sig_key)
            sig_news = mkt_news.get(sig_key, 0) + guardian.get(sig_key, 0)
            snap["news_volumes_by_market"][market_name][sig_key] = sig_news
            if wiki is not None and is_per_market:
                # Blend wiki trend shape with per-market news intensity
                sig_max = max((newsapi_raw.get(m, {}).get(sig_key, 0) for m in MARKETS.values()), default=1) or 1
                news_norm = min(99, round((sig_news / sig_max) * 99))
                snap["markets"][market_name][sig_key] = round(wiki * 0.45 + news_norm * 0.55, 1)
            else:
                snap["markets"][market_name][sig_key] = wiki

    # Flat global rollup for backwards compat
    for sig_key in signals:
        na_src = pulse.get("news_volumes", {}).get("newsapi_global") or {}
        na = na_src.get(sig_key, 0)
        gd = guardian.get(sig_key, 0)
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

    # ── NewsAPI (per market — one batched query each) ────────────────────────
    log.info("\n📰 NewsAPI (per market)...")
    if newsapi_key:
        news_vols_by_market: dict = {m: {} for m in MARKETS.values()}
        newsapi_ok = False
        for market_name in MARKETS.values():
            geo = MARKET_NEWS_TERMS.get(market_name, market_name)
            # Single broad query per market — counts total news volume, not per-signal
            r = safe_get("https://newsapi.org/v2/everything",
                         params={"q": geo, "from": from_date, "language": "en",
                                 "pageSize": 1, "apiKey": newsapi_key})
            if r and r.status_code == 200:
                total = r.json().get("totalResults", 0)
                # Distribute evenly across signals as a rough proxy
                per_sig = max(1, round(total / len(signals)))
                for sig_key in signals:
                    news_vols_by_market[market_name][sig_key] = per_sig
                log.info(f"  ✓ {market_name}: {total} total articles (~{per_sig}/signal)")
                newsapi_ok = True
            else:
                code = r.status_code if r else "timeout"
                log.warning(f"  ✗ {market_name}: {code} — skipping")
                for sig_key in signals:
                    news_vols_by_market[market_name][sig_key] = 0
            time.sleep(0.5)
        if newsapi_ok:
            result["news_volumes"]["newsapi"] = news_vols_by_market
            result["news_volumes"]["newsapi_global"] = {
                sig: sum(news_vols_by_market[m].get(sig, 0) for m in MARKETS.values())
                for sig in signals
            }
            result["sources_live"].append("newsapi")
        else:
            result["sources_failed"].append("newsapi")
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



# ── AI Summaries (template-based — deterministic, no external API needed) ─────

def generate_market_summary(market: str, data: dict, config: dict) -> str:
    """Generate a data-driven 3-paragraph market brief directly from signals."""
    from datetime import timezone as tz
    categories    = config.get("categories", {})
    newsapi_raw   = data.get("news_volumes", {}).get("newsapi", {})
    guardian      = data.get("news_volumes", {}).get("guardian", {})
    rss           = data.get("global", {}).get("rss_trends", {}).get(market, {})
    is_per_market = isinstance(next(iter(newsapi_raw.values()), None), dict)
    mkt_news      = newsapi_raw.get(market, {}) if is_per_market else newsapi_raw
    is_ramadan    = bool(data.get("ramadan_active") and config.get("ramadan_active"))

    # Score every active signal by news volume
    all_signals: dict = {}
    for ck, cat in categories.items():
        if cat.get("ramadan_only") and not is_ramadan:
            continue
        for sk in cat.get("signals", {}).keys():
            score = (mkt_news.get(sk, 0) + guardian.get(sk, 0))
            all_signals[sk] = {"score": score, "cat": ck, "cat_label": cat["label"]}

    ranked   = sorted(all_signals.items(), key=lambda x: x[1]["score"], reverse=True)
    top2     = ranked[:2]

    cat_scores: dict = {}
    for sk, info in all_signals.items():
        cat_scores[info["cat"]] = cat_scores.get(info["cat"], 0) + info["score"]
    top_cat_key   = max(cat_scores, key=cat_scores.get) if cat_scores else ""
    top_cat_label = categories.get(top_cat_key, {}).get("label", "")

    sport_pct  = rss.get("sport_entertainment_pct", 0)
    crisis_pct = rss.get("crisis_pct", 0)
    trending   = rss.get("top_topics", [])[:3]
    trend_str  = ", ".join(trending) if trending else None

    def sig_label(sk: str) -> str:
        return sk.replace("_", " ")

    # P1: Consumer Pulse
    p1_sigs    = " and ".join(f"**{sig_label(s)}**" for s, _ in top2)
    mood       = "crisis-driven" if crisis_pct > sport_pct else "entertainment-led"
    ramadan_p1 = " Ramadan is amplifying late-night activity and iftar-related consumption." if is_ramadan else ""
    p1 = (f"Consumer attention in {market} is concentrated around {p1_sigs}, "
          f"which together dominate the signal landscape. "
          f"The overall mood is {mood}, with {top_cat_label} emerging as the strongest category.{ramadan_p1}")

    # P2: What's Driving It
    drivers = []
    if crisis_pct >= 20:
        drivers.append(f"elevated regional crisis coverage ({crisis_pct}% of trending topics)")
    if sport_pct >= 20:
        drivers.append(f"strong sports and entertainment engagement ({sport_pct}%)")
    if is_ramadan:
        drivers.append("the Ramadan consumption cycle shifting peak hours to evenings")
    if trend_str:
        drivers.append(f"trending conversations around {trend_str}")
    if not drivers:
        drivers.append("a mix of seasonal and regional factors")
    p2 = (f"This pattern is being driven by {'; '.join(drivers)}. "
          f"The {sig_label(top2[0][0])} signal in particular reflects the current media environment "
          f"across MENA, with audiences actively tracking developing stories alongside daily life.")

    # P3: Media Implication
    if crisis_pct >= 20:
        action = (f"avoid hard promotional messaging this week — "
                  f"contextual and empathy-led creatives will perform better alongside "
                  f"{sig_label(top2[0][0])} content environments")
    elif is_ramadan:
        action = (f"activate Ramadan prime time (9–11pm) — iftar-moment sponsorships "
                  f"and evening digital placements capture peak {sig_label(top2[1][0])} engagement")
    else:
        action = (f"lean into {top_cat_label.lower()} environments — "
                  f"the {sig_label(top2[0][0])} signal suggests audiences are primed "
                  f"for discovery content over hard sell this week")
    p3 = f"For media planners in {market}: {action}."

    return f"{p1}\n\n{p2}\n\n{p3}"


def generate_all_summaries(data: dict, config: dict) -> dict:
    markets = ["UAE", "KSA", "Kuwait", "Qatar"]
    log.info("\n🤖 Generating market summaries...")
    summaries = {}
    for market in markets:
        try:
            text = generate_market_summary(market, data, config)
            summaries[market] = text
            log.info(f"  ✓ {market} ({len(text.split())} words)")
        except Exception as e:
            log.warning(f"  ✗ {market}: {e}")
    return summaries


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
