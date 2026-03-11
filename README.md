# Crisis Pulse

**Real-time consumer signal dashboard for MENA markets.**

Built for WPP MENA crisis reporting. Monitors behavioral and media signals across UAE, KSA, Kuwait, and Qatar — refreshed daily, zero infrastructure cost.

---

## What It Does

Crisis Pulse aggregates five independent data sources into a single dashboard, tracking how consumer attention shifts during periods of economic or social disruption. It is designed to surface early signals across gaming/escapism, wellness, price sensitivity, delivery behavior, and news consumption — before they appear in paid research.

---

## Data Sources

| Source | What It Measures | Auth Required |
|---|---|---|
| **Wikipedia Pageviews** | Daily interest index per signal topic (normalized 0–100) | None |
| **Google Trends RSS** | Trending search topics per market, classified by category | None |
| **NewsAPI** | Global article volume per signal keyword over 7 days | Free API key |
| **The Guardian API** | Editorial article volume per signal keyword over 7 days | Free API key |
| **Twitch API** | Live global gaming viewership and top titles | Free app registration |

All sources are free tier. No paid APIs. No cloud server.

---

## Markets

UAE · KSA · Kuwait · Qatar

---

## Architecture

```
GitHub Actions (daily 09:00 GST)
    └── scripts/collect.py
            ├── Wikipedia Pageviews API
            ├── Google Trends RSS
            ├── NewsAPI
            ├── Guardian API
            └── Twitch API
                    ↓
            public/pulse_data.json  (committed to repo)
                    ↓
            Vercel (auto-deploys on push)
                    ↓
            src/App.tsx  (reads /pulse_data.json at load)
```

No backend server. The collector runs on GitHub's infrastructure, writes a static JSON file, and Vercel serves it. The dashboard is a pure frontend React app.

---

## Dashboard Sections

**Signal Snapshot** — Latest Wikipedia interest index per signal for the selected market, with week-on-week delta badges.

**Trending Topics** — Per-market Google RSS breakdown showing today's top trending searches, classified into sport/entertainment vs crisis categories.

**Behavioral Trends** — 7-day Wikipedia pageview trend lines for all signals, with a per-signal deep-dive view. Market-switchable.

**News Volume** — Side-by-side NewsAPI vs Guardian article counts per signal over the past 7 days.

**Live Gaming** — Twitch total live viewership and top 5 titles by viewer count, pulled at collection time.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/raghavhvr/crisis-pulse
cd crisis-pulse
```

### 2. Install frontend dependencies

```bash
npm install
npm run dev
```

### 3. Configure API keys

Create a `.env` file in the repo root (never committed):

```
NEWSAPI_KEY=your_key_here
GUARDIAN_KEY=your_key_here
TWITCH_CLIENT_ID=your_client_id_here
TWITCH_CLIENT_SECRET=your_client_secret_here
```

Get free keys from:
- NewsAPI → [newsapi.org](https://newsapi.org)
- Guardian → [open-platform.theguardian.com](https://open-platform.theguardian.com)
- Twitch → [dev.twitch.tv/console](https://dev.twitch.tv/console)

### 4. Run the collector locally

```bash
pip install -r requirements.txt
python scripts/collect.py
```

This writes `public/pulse_data.json`. The dashboard reads from this file.

### 5. Deploy

**Vercel** — connect the GitHub repo, set framework to Vite, deploy. Vercel auto-redeploys on every push.

**GitHub Actions** — add your four API keys as repository secrets (Settings → Secrets → Actions). The workflow runs daily at 05:00 UTC and commits fresh data automatically.

---

## GitHub Actions Secrets Required

| Secret | Source |
|---|---|
| `NEWSAPI_KEY` | newsapi.org |
| `GUARDIAN_KEY` | open-platform.theguardian.com |
| `TWITCH_CLIENT_ID` | dev.twitch.tv |
| `TWITCH_CLIENT_SECRET` | dev.twitch.tv |

---

## Local Development

```bash
npm run dev       # start Vite dev server
python scripts/collect.py   # refresh data manually
```

The dashboard reads from `/pulse_data.json` at page load. Re-run the collector any time to update the data locally.

---

## Requirements

**Frontend** — React 18, Vite, Recharts, TypeScript

**Collector** — Python 3.11+, `requests`, `python-dotenv`

---

## License

Internal tool — WPP MENA. Not for public redistribution.
