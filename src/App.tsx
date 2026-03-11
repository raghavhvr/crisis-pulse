import { useState, useEffect, useRef } from "react";
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis,
  Tooltip, ResponsiveContainer, Cell, RadarChart,
  Radar, PolarGrid, PolarAngleAxis
} from "recharts";

const DATA_URL    = "/pulse_data.json";
const CONFIG_URL  = "/signals_config.json";
const HISTORY_URL = "/pulse_history.json";
const GH_OWNER    = "raghavhvr";
const GH_REPO     = "crisis-pulse";
const GH_PATH     = "public/signals_config.json";

const MARKET_FLAGS: Record<string,string> = {
  UAE:"🇦🇪", KSA:"🇸🇦", Kuwait:"🇰🇼", Qatar:"🇶🇦"
};

function fmt(n:number){ return n>=1000?`${(n/1000).toFixed(1)}K`:String(n); }

const CustomTooltip = ({active,payload,label}:any) => {
  if(!active||!payload?.length) return null;
  return (
    <div style={{background:"#080e14",border:"1px solid #1e2d3d",borderRadius:6,padding:"10px 14px",fontSize:11,lineHeight:1.9}}>
      <div style={{fontFamily:"'DM Mono',monospace",color:"#4a6070",fontSize:10,marginBottom:4}}>{label}</div>
      {payload.map((p:any)=>(
        <div key={p.name} style={{color:p.color}}>
          <span style={{color:"#4a6070"}}>{p.name}: </span><strong>{p.value}</strong>
        </div>
      ))}
    </div>
  );
};

// ── Ramadan banner ────────────────────────────────────────────────────────────
function RamadanBanner({endDate}:{endDate:string}){
  const days = Math.max(0,Math.ceil((new Date(endDate).getTime()-Date.now())/(86400000)));
  return (
    <div className="ramadan-banner">
      <span className="ramadan-moon">☽</span>
      <span className="ramadan-text">Ramadan Mode Active</span>
      <span className="ramadan-sub">Signals adjusted for Ramadan consumption patterns · {days} days remaining</span>
    </div>
  );
}

// ── Category score card ───────────────────────────────────────────────────────
function CategoryCard({
  cat, catKey, signals, markets, activeMarket, isActive, onClick,
  newsapi, guardian, rss
}:{
  cat:any, catKey:string, signals:Record<string,any>,
  markets:any, activeMarket:string, isActive:boolean, onClick:()=>void,
  newsapi:any, guardian:any, rss:any
}){
  const catSignals = Object.keys(signals).filter(k=>signals[k].category===catKey);

  // News volume: per-market from NewsAPI geo-filtered queries
  const newsVolumes = catSignals.map(k=>(newsapi[k]||0)+(guardian[k]||0));
  const newsTotal   = newsVolumes.reduce((a,b)=>a+b,0);
  const newsMax     = Math.max(...newsVolumes,1);

  // Normalise news total to 0-99 score (log scale so large values don't dominate)
  const newsScore = newsTotal > 0
    ? Math.min(99, Math.round(Math.log(newsTotal+1)/Math.log(5000)*99))
    : 0;

  // Wikipedia: global index as secondary context
  const wikiValues = catSignals.map(k=>{
    const v = markets[activeMarket]?.[k];
    return Array.isArray(v) ? v[v.length-1] : null;
  }).filter(v=>v!==null) as number[];
  const wikiAvg = wikiValues.length
    ? Math.round(wikiValues.reduce((a,b)=>a+b,0)/wikiValues.length)
    : null;

  // RSS market signal
  const rssMarket = rss[activeMarket]||{};
  let rssSignal = 0;
  if(catKey==="crisis_awareness") rssSignal = rssMarket.crisis_pct||0;
  else if(catKey==="escapism")    rssSignal = rssMarket.sport_entertainment_pct||0;
  else rssSignal = Math.round(((rssMarket.sport_entertainment_pct||0)+(rssMarket.crisis_pct||0))/2);

  // Primary display score = news volume (market-specific) + rss modifier
  const hasNewsData = newsTotal > 0;
  const displayScore = hasNewsData
    ? Math.min(99, Math.round(newsScore * 0.7 + rssSignal * 0.3))
    : (wikiAvg ?? 0);

  // Sparkline: per-signal news volumes (market-specific bars)
  const hasRealData = hasNewsData || (wikiValues.length > 0);
  const sparkData = hasNewsData
    ? catSignals.map(k=>{
        const v = (newsapi[k]||0)+(guardian[k]||0);
        return Math.round((v/newsMax)*90)+5;
      })
    : Array.from({length:8},(_,i)=>20+i*2); // placeholder
  const sparkMax = Math.max(...sparkData,1);
  const trend = sparkData.length>=2 ? sparkData[sparkData.length-1]-sparkData[0] : 0;

  return (
    <div className={`cat-card ${isActive?"active":""}`}
      style={{"--cat-color":cat.color} as any}
      onClick={onClick}>
      <div className="cat-card-header">
        <span className="cat-icon">{cat.icon}</span>
        <div className="cat-meta">
          <div className="cat-label">{cat.label}</div>
          <div className="cat-sig-count">{catSignals.length} signals
            {!hasRealData && <span style={{color:"var(--muted)",marginLeft:6,fontSize:8}}>· pending run</span>}
          </div>
        </div>
        <div className="cat-score-wrap">
          <div className="cat-score" style={{opacity:hasRealData?1:0.4}}>{displayScore}</div>
          <div className={`cat-trend ${trend>0?"up":trend<0?"down":"flat"}`}>
            {trend>0?"▲":trend<0?"▼":"→"} {Math.abs(Math.round(trend))}
          </div>
        </div>
      </div>
      {/* RSS market bar — this DOES differ per market */}
      {rssSignal > 0 && (
        <div style={{marginBottom:8}}>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
            <span style={{fontFamily:"var(--mono)",fontSize:8,color:"var(--muted)"}}>
              {catKey==="crisis_awareness"?"CRISIS SIGNAL":catKey==="escapism"?"SPORT/ENT SIGNAL":"RSS SIGNAL"} · {activeMarket}
            </span>
            <span style={{fontFamily:"var(--mono)",fontSize:8,color:cat.color}}>{rssSignal}%</span>
          </div>
          <div style={{height:3,background:"var(--border)",borderRadius:2,overflow:"hidden"}}>
            <div style={{height:"100%",width:`${rssSignal}%`,background:cat.color,
              borderRadius:2,transition:"width .4s"}}/>
          </div>
        </div>
      )}
      <div className="cat-sparkline">
        {sparkData.map((v,i)=>(
          <div key={i} className="spark-bar"
            style={{height:`${Math.round((v/sparkMax)*28)+2}px`,background:cat.color,
              opacity:hasRealData?(i===sparkData.length-1?1:0.35+i*0.08):0.2}} />
        ))}
      </div>
      <div className="cat-hypothesis">{cat.hypothesis}</div>
    </div>
  );
}

// ── Signal row (expandable detail) ────────────────────────────────────────────
function SignalRow({sigKey,sig,markets,activeMarket,dates,newsapi,guardian}:{
  sigKey:string,sig:any,markets:any,activeMarket:string,
  dates:string[],newsapi:any,guardian:any
}){
  const vals = markets[activeMarket]?.[sigKey]||[];
  const curr = vals[vals.length-1]??0;
  const prev = vals[vals.length-2]??curr;
  const pct  = prev ? Math.round(((curr-prev)/prev)*100) : 0;
  const chartData = dates.map((d:string,i:number)=>({date:d,value:vals[i]??null}));
  const news  = (newsapi[sigKey]||0)+(guardian[sigKey]||0); // newsapi already market-filtered

  return (
    <div className="signal-row">
      <div className="signal-row-left">
        <div className="signal-dot" style={{background:sig.color||"#4a6070"}} />
        <div className="signal-name">{sig.label}</div>
      </div>
      <div className="signal-sparkline-wrap">
        <ResponsiveContainer width={120} height={28}>
          <LineChart data={chartData}>
            <Line type="monotone" dataKey="value" stroke={sig.color||"#4a6070"}
              strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="signal-row-right">
        <div className="signal-val">{curr}</div>
        <div className={`signal-pct ${pct>0?"up":pct<0?"down":"flat"}`}>
          {pct>0?"▲":pct<0?"▼":"→"}{Math.abs(pct)}%
        </div>
        <div className="signal-news">{fmt(news)} art.</div>
      </div>
    </div>
  );
}

// ── Settings panel ────────────────────────────────────────────────────────────
function SettingsPanel({config,onClose,onSave}:{config:any,onClose:()=>void,onSave:(c:any)=>Promise<void>}){
  const [draft,setDraft]     = useState(()=>JSON.parse(JSON.stringify(config)));
  const [pat,setPat]         = useState(()=>localStorage.getItem("gh_pat")||"");
  const [saving,setSaving]   = useState(false);
  const [msg,setMsg]         = useState("");

  function toggle(catKey:string,sigKey:string,field:string,val:string){
    setDraft((d:any)=>({...d,categories:{...d.categories,[catKey]:{...d.categories[catKey],
      signals:{...d.categories[catKey].signals,[sigKey]:{...d.categories[catKey].signals[sigKey],[field]:val}}}}}));
  }

  async function handleSave(){
    if(!pat){setMsg("⚠ Enter GitHub PAT");return;}
    localStorage.setItem("gh_pat",pat);
    setSaving(true); setMsg("");
    try {
      await onSave({...draft,last_updated:new Date().toISOString(),updated_by:"dashboard"});
      setMsg("✓ Saved — takes effect on next collector run");
    } catch(e:any){ setMsg(`✗ ${e.message}`); }
    setSaving(false);
  }

  return (
    <div className="overlay" onClick={e=>{if((e.target as any).classList.contains("overlay"))onClose();}}>
      <div className="settings-panel">
        <div className="sp-header">
          <span style={{fontFamily:"'DM Mono',monospace",fontSize:12,letterSpacing:2}}>⚙ SIGNAL CONFIGURATION</span>
          <button className="sp-close" onClick={onClose}>✕</button>
        </div>
        <div className="sp-body">
          <div className="sp-pat-row">
            <label className="sp-label">GitHub PAT (repo:write)</label>
            <input type="password" className="sp-input" value={pat}
              placeholder="ghp_xxxxxxxxxxxx"
              onChange={e=>setPat(e.target.value)} />
          </div>
          <div className="sp-divider"/>
          {Object.entries(draft.categories).map(([catKey,cat]:any)=>(
            <div key={catKey} className="sp-cat">
              <div className="sp-cat-header" style={{borderLeftColor:cat.color}}>
                {cat.icon} {cat.label}
                {cat.ramadan_only&&<span className="sp-ramadan-badge">☽ Ramadan only</span>}
              </div>
              {Object.entries(cat.signals).map(([sigKey,sig]:any)=>(
                <div key={sigKey} className="sp-sig-row">
                  <div className="sp-sig-name">{sig.label}</div>
                  <div className="sp-fields">
                    <div className="sp-field-group">
                      <label className="sp-field-label">Wikipedia</label>
                      <input className="sp-input sm" value={sig.wiki}
                        onChange={e=>toggle(catKey,sigKey,"wiki",e.target.value)} />
                    </div>
                    <div className="sp-field-group">
                      <label className="sp-field-label">NewsAPI</label>
                      <input className="sp-input sm" value={sig.news}
                        onChange={e=>toggle(catKey,sigKey,"news",e.target.value)} />
                    </div>
                    <div className="sp-field-group">
                      <label className="sp-field-label">Guardian</label>
                      <input className="sp-input sm" value={sig.guardian}
                        onChange={e=>toggle(catKey,sigKey,"guardian",e.target.value)} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className="sp-footer">
          {msg&&<div className={`sp-msg ${msg.startsWith("✓")?"ok":"err"}`}>{msg}</div>}
          <button className="sp-cancel" onClick={onClose}>Cancel</button>
          <button className="sp-save" onClick={handleSave} disabled={saving}>
            {saving?"Saving…":"Save to GitHub"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App(){
  const [data,         setData]         = useState<any>(null);
  const [config,       setConfig]       = useState<any>(null);
  const [history,      setHistory]      = useState<any[]>([]);
  const [error,        setError]        = useState<string|null>(null);
  const [activeMarket, setActiveMarket] = useState("UAE");
  const [activeCat,    setActiveCat]    = useState<string|null>(null);
  const [historyDays,  setHistoryDays]  = useState(30);
  const [showSettings, setShowSettings] = useState(false);
  const [configSha,    setConfigSha]    = useState("");

  useEffect(()=>{
    Promise.all([
      fetch(DATA_URL).then(r=>{ if(!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }),
      fetch(CONFIG_URL).then(r=>r.ok?r.json():null),
      fetch(HISTORY_URL).then(r=>r.ok?r.json():[]).catch(()=>[]),
    ]).then(([d,c,h])=>{
      setData(d);
      if(c){ setConfig(c); setActiveCat(Object.keys(c.categories)[0]||null); }
      if(Array.isArray(h)) setHistory(h);
    }).catch(e=>setError(e.message));
  },[]);

  useEffect(()=>{
    if(!showSettings) return;
    fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${GH_PATH}`)
      .then(r=>r.json()).then(d=>setConfigSha(d.sha||"")).catch(()=>{});
  },[showSettings]);

  async function saveConfig(newConfig:any){
    const pat = localStorage.getItem("gh_pat")||"";
    if(!pat) throw new Error("No GitHub PAT");
    const content = btoa(unescape(encodeURIComponent(JSON.stringify(newConfig,null,2))));
    const body:any = {message:"config: update signals from dashboard",content,branch:"main"};
    if(configSha) body.sha=configSha;
    const res = await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${GH_PATH}`,{
      method:"PUT",
      headers:{"Authorization":`Bearer ${pat}`,"Content-Type":"application/json","X-GitHub-Api-Version":"2022-11-28"},
      body:JSON.stringify(body),
    });
    if(!res.ok){ const e=await res.json(); throw new Error(e.message||`GitHub ${res.status}`); }
    setConfig(newConfig);
    setConfigSha((await res.json()).content?.sha||configSha);
  }

  if(error) return (
    <div className="loading-screen">
      <div style={{fontSize:32,marginBottom:8}}>⚠</div>
      <div style={{fontFamily:"'DM Mono',monospace",color:"#f72585",fontSize:12}}>Failed to load pulse data</div>
      <div style={{fontSize:11,color:"#4a6070",marginTop:4}}>{error}</div>
      <button onClick={()=>window.location.reload()} className="retry-btn">↺ Retry</button>
    </div>
  );

  if(!data||!config) return (
    <div className="loading-screen">
      <div className="loader">
        {[0,1,2,3,4].map(i=>(
          <div key={i} className="loader-bar" style={{animationDelay:`${i*0.12}s`}}/>
        ))}
      </div>
      <div className="loading-text">Pulling latest signals…</div>
    </div>
  );

  // Flatten signals with category info
  const flatSigs: Record<string,any> = {};
  Object.entries(config.categories).forEach(([catKey,cat]:any)=>{
    Object.entries(cat.signals).forEach(([sigKey,sig]:any)=>{
      flatSigs[sigKey]={...sig,category:catKey,color:cat.color,icon:cat.icon};
    });
  });

  const categories   = config.categories as Record<string,any>;
  const catKeys      = Object.keys(categories);
  const markets      = data.markets||{};
  const global       = data.global||{};
  const rss          = global.rss_trends||{};
  const twitch       = global.twitch||{};
  // newsapi is now per-market: { UAE: { gaming: 12, ... }, KSA: ... }
  // or legacy flat: { gaming: 28, ... }
  const newsapiRaw   = data.news_volumes?.newsapi||{};
  const newsapiGlobal= data.news_volumes?.newsapi_global||{};
  const isPerMarket  = newsapiRaw[activeMarket] !== undefined;
  const newsapi      = isPerMarket ? (newsapiRaw[activeMarket]||{}) : newsapiRaw;
  const guardian     = data.news_volumes?.guardian||{};
  const dates        = data.dates||[];
  const sources      = data.sources_live||[];
  const isRamadan    = data.ramadan_active&&config.ramadan_active;
  const ramadanEnd   = config.ramadan_end||"";

  const activeCatObj  = activeCat ? categories[activeCat] : null;
  const activeSigKeys = activeCat
    ? Object.keys(categories[activeCat]?.signals||{})
    : Object.keys(flatSigs);

  // History chart data
  const historySlice = history.slice(-historyDays);
  const historyChart = historySlice.map((rec:any)=>{
    const row:any={date:rec.date?.slice(5)};
    catKeys.forEach(ck=>{
      const sigs = Object.keys(categories[ck]?.signals||{});
      const vals = Object.values(MARKET_FLAGS).flatMap(
        m=>sigs.map(s=>rec.markets?.[m]?.[s]).filter((v:any)=>v!=null)
      ) as number[];
      row[ck] = vals.length ? Math.round(vals.reduce((a:number,b:number)=>a+b,0)/vals.length*10)/10 : null;
    });
    return row;
  });

  // Radar data — category scores for active market
  const radarData = catKeys.map(ck=>{
    const cat = categories[ck];
    const sigs = Object.keys(cat.signals||{});
    const vals = sigs.map(s=>{
      const v = markets[activeMarket]?.[s];
      return Array.isArray(v) ? v[v.length-1] : (v??0);
    }).filter(v=>v!=null) as number[];
    const avg = vals.length ? Math.round(vals.reduce((a,b)=>a+b,0)/vals.length) : 0;
    return {category:cat.label.split("&")[0].trim(), value:avg, fullMark:100};
  });

  const fetchedAt  = new Date(data.fetched_at);
  const timeAgo    = Math.round((Date.now()-fetchedAt.getTime())/60000);
  const timeAgoStr = timeAgo<60?`${timeAgo}m ago`:`${Math.round(timeAgo/60)}h ago`;

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@300;400;500&family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');
        *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
        :root{
          --bg:#060a0f; --s1:#0a1018; --s2:#0e161f; --s3:#121d27;
          --border:#1a2535; --border2:#243040;
          --text:#b8c8d8; --muted:#3d5060; --bright:#e0ecf4;
          --cyan:#00e5c8; --pink:#f0226e; --yellow:#f5d020;
          --orange:#f07020; --purple:#8040e0; --green:#20d080;
          --mono:"DM Mono",monospace; --sans:"DM Sans",sans-serif;
          --display:"Syne",sans-serif;
        }
        html{scroll-behavior:smooth;}
        body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh;
          background-image:radial-gradient(ellipse at 20% 0%,rgba(0,180,160,0.04) 0%,transparent 60%),
                           radial-gradient(ellipse at 80% 100%,rgba(120,40,200,0.04) 0%,transparent 60%);}

        /* ── Header ── */
        .hdr{
          display:flex;align-items:center;justify-content:space-between;
          padding:14px 32px;border-bottom:1px solid var(--border);
          background:rgba(6,10,15,0.95);backdrop-filter:blur(12px);
          position:sticky;top:0;z-index:100;
        }
        .hdr-left{display:flex;align-items:center;gap:16px;}
        .pulse-ring{
          width:12px;height:12px;border-radius:50%;background:var(--cyan);
          box-shadow:0 0 0 0 rgba(0,229,200,0.4);
          animation:ring 2.5s ease-in-out infinite;
        }
        @keyframes ring{0%{box-shadow:0 0 0 0 rgba(0,229,200,0.5);}70%{box-shadow:0 0 0 10px rgba(0,229,200,0);}100%{box-shadow:0 0 0 0 rgba(0,229,200,0);}}
        .hdr-title{font-family:var(--display);font-size:16px;font-weight:800;letter-spacing:4px;color:var(--bright);text-transform:uppercase;}
        .hdr-sub{font-family:var(--mono);font-size:9px;color:var(--muted);letter-spacing:2px;margin-top:2px;}
        .hdr-right{display:flex;align-items:center;gap:12px;flex-wrap:wrap;}
        .chip{font-family:var(--mono);font-size:9px;letter-spacing:1px;padding:3px 8px;border-radius:2px;border:1px solid;}
        .chip.live{border-color:rgba(0,229,200,0.3);color:var(--cyan);background:rgba(0,229,200,0.05);}
        .chip.dead{border-color:var(--border);color:var(--muted);}
        .ts{font-family:var(--mono);font-size:10px;color:var(--muted);}
        .sp-trigger{
          font-family:var(--mono);font-size:10px;letter-spacing:1px;
          padding:6px 14px;border:1px solid var(--border2);border-radius:3px;
          background:transparent;color:var(--muted);cursor:pointer;transition:all .15s;
        }
        .sp-trigger:hover{border-color:var(--cyan);color:var(--cyan);}

        /* ── Ramadan banner ── */
        .ramadan-banner{
          display:flex;align-items:center;gap:12px;padding:10px 32px;
          background:linear-gradient(90deg,rgba(245,208,32,0.08),rgba(245,208,32,0.03));
          border-bottom:1px solid rgba(245,208,32,0.15);
        }
        .ramadan-moon{font-size:16px;}
        .ramadan-text{font-family:var(--display);font-size:13px;font-weight:700;color:var(--yellow);letter-spacing:1px;}
        .ramadan-sub{font-family:var(--mono);font-size:10px;color:rgba(245,208,32,0.5);letter-spacing:1px;}

        /* ── Market tabs ── */
        .market-bar{
          display:flex;gap:0;border-bottom:1px solid var(--border);
          background:var(--s1);padding:0 32px;overflow-x:auto;
        }
        .mkt-tab{
          font-family:var(--mono);font-size:11px;letter-spacing:1px;
          padding:12px 20px;border:none;background:transparent;
          color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;
          transition:all .15s;white-space:nowrap;
        }
        .mkt-tab:hover{color:var(--text);}
        .mkt-tab.active{color:var(--cyan);border-bottom-color:var(--cyan);}

        /* ── Main layout ── */
        .main{padding:28px 32px;display:flex;flex-direction:column;gap:32px;max-width:1500px;margin:0 auto;}

        /* ── Section header ── */
        .sec{font-family:var(--mono);font-size:9px;letter-spacing:3px;color:var(--muted);
          text-transform:uppercase;margin-bottom:16px;display:flex;align-items:center;gap:12px;}
        .sec::after{content:'';flex:1;height:1px;background:var(--border);}

        /* ── Category grid ── */
        .cat-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;}
        .cat-card{
          background:var(--s1);border:1px solid var(--border);border-radius:8px;
          padding:16px;cursor:pointer;transition:all .2s;position:relative;overflow:hidden;
          border-left:3px solid var(--cat-color,#333);
        }
        .cat-card::before{
          content:'';position:absolute;inset:0;
          background:linear-gradient(135deg,rgba(255,255,255,0.02),transparent);
          pointer-events:none;
        }
        .cat-card:hover{border-color:var(--cat-color,#333);background:var(--s2);}
        .cat-card.active{background:var(--s2);border-color:var(--cat-color,#333);
          box-shadow:0 0 0 1px var(--cat-color,#333),inset 0 0 40px rgba(0,0,0,0.3);}
        .cat-card-header{display:flex;align-items:flex-start;gap:10px;margin-bottom:12px;}
        .cat-icon{font-size:18px;flex-shrink:0;margin-top:1px;}
        .cat-meta{flex:1;min-width:0;}
        .cat-label{font-family:var(--display);font-size:12px;font-weight:700;color:var(--bright);line-height:1.3;}
        .cat-sig-count{font-family:var(--mono);font-size:9px;color:var(--muted);margin-top:3px;}
        .cat-score-wrap{text-align:right;flex-shrink:0;}
        .cat-score{font-family:var(--mono);font-size:22px;font-weight:500;color:var(--cat-color,#fff);line-height:1;}
        .cat-trend{font-family:var(--mono);font-size:9px;margin-top:3px;}
        .cat-trend.up{color:var(--cyan);}
        .cat-trend.down{color:var(--pink);}
        .cat-trend.flat{color:var(--muted);}
        .cat-sparkline{display:flex;align-items:flex-end;gap:2px;height:30px;margin-bottom:10px;}
        .spark-bar{width:100%;border-radius:1px;transition:height .3s;}
        .cat-hypothesis{font-size:10px;color:var(--muted);line-height:1.5;font-style:italic;}

        /* ── Signal detail panel ── */
        .detail-panel{background:var(--s1);border:1px solid var(--border);border-radius:8px;overflow:hidden;}
        .dp-header{
          display:flex;align-items:center;justify-content:space-between;
          padding:16px 20px;border-bottom:1px solid var(--border);
          background:var(--s2);
        }
        .dp-title{font-family:var(--display);font-size:14px;font-weight:700;color:var(--bright);}
        .dp-hypothesis{font-size:11px;color:var(--muted);margin-top:2px;font-style:italic;}
        .dp-body{display:grid;grid-template-columns:1fr 340px;gap:0;}
        .dp-signals{padding:16px 20px;border-right:1px solid var(--border);}
        .dp-chart-panel{padding:16px 20px;}

        /* ── Signal rows ── */
        .signal-row{
          display:flex;align-items:center;gap:12px;padding:10px 0;
          border-bottom:1px solid var(--border);
        }
        .signal-row:last-child{border-bottom:none;}
        .signal-row-left{display:flex;align-items:center;gap:8px;width:160px;flex-shrink:0;}
        .signal-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
        .signal-name{font-size:12px;color:var(--text);}
        .signal-sparkline-wrap{flex:1;}
        .signal-row-right{display:flex;align-items:center;gap:12px;flex-shrink:0;}
        .signal-val{font-family:var(--mono);font-size:14px;color:var(--bright);width:30px;text-align:right;}
        .signal-pct{font-family:var(--mono);font-size:10px;width:40px;text-align:right;}
        .signal-pct.up{color:var(--cyan);}
        .signal-pct.down{color:var(--pink);}
        .signal-pct.flat{color:var(--muted);}
        .signal-news{font-family:var(--mono);font-size:10px;color:var(--muted);width:55px;text-align:right;}

        /* ── Trending topics ── */
        .topics-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
        .topic-card{background:var(--s1);border:1px solid var(--border);border-radius:8px;padding:16px;}
        .tc-header{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
        .tc-flag{font-size:20px;}
        .tc-name{font-family:var(--display);font-size:13px;font-weight:700;color:var(--bright);}
        .mood-bar{display:flex;height:3px;border-radius:2px;overflow:hidden;gap:1px;margin-bottom:8px;}
        .mood-labels{display:flex;justify-content:space-between;font-family:var(--mono);font-size:8px;color:var(--muted);margin-bottom:10px;}
        .topic-item{font-size:11px;color:var(--text);padding:4px 0;border-bottom:1px solid var(--border);display:flex;gap:6px;}
        .topic-item:last-child{border-bottom:none;}
        .topic-num{font-family:var(--mono);color:var(--muted);font-size:10px;flex-shrink:0;}

        /* ── Radar + long-term ── */
        .analysis-grid{display:grid;grid-template-columns:320px 1fr;gap:16px;}
        .card{background:var(--s1);border:1px solid var(--border);border-radius:8px;padding:20px;}
        .card-title{font-family:var(--mono);font-size:10px;letter-spacing:2px;color:var(--muted);margin-bottom:4px;}
        .card-sub{font-size:11px;color:var(--muted);margin-bottom:16px;font-style:italic;}

        /* ── Period buttons ── */
        .period-btns{display:flex;gap:6px;margin-bottom:16px;}
        .period-btn{
          font-family:var(--mono);font-size:9px;letter-spacing:1px;
          padding:4px 10px;border:1px solid var(--border);border-radius:2px;
          background:transparent;color:var(--muted);cursor:pointer;transition:all .15s;
        }
        .period-btn:hover{border-color:var(--cyan);color:var(--cyan);}
        .period-btn.active{border-color:var(--cyan);color:var(--cyan);background:rgba(0,229,200,0.07);}

        /* ── Twitch ── */
        .twitch-row{display:grid;grid-template-columns:auto 1fr;gap:24px;align-items:center;}
        .twitch-stat{padding-right:24px;border-right:1px solid var(--border);text-align:center;}
        .twitch-num{font-family:var(--mono);font-size:38px;color:var(--cyan);line-height:1;}
        .twitch-lbl{font-family:var(--mono);font-size:9px;color:var(--muted);letter-spacing:2px;margin-top:4px;}
        .game-rows{display:flex;flex-direction:column;gap:9px;}
        .game-row{display:flex;align-items:center;gap:10px;}
        .game-name{font-size:11px;color:var(--text);width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        .game-bar-bg{flex:1;height:5px;background:var(--border);border-radius:3px;overflow:hidden;}
        .game-bar-fg{height:100%;border-radius:3px;}
        .game-views{font-family:var(--mono);font-size:10px;color:var(--muted);width:48px;text-align:right;}

        /* ── Loading ── */
        .loading-screen{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:20px;}
        .loader{display:flex;align-items:flex-end;gap:4px;height:40px;}
        .loader-bar{
          width:6px;border-radius:3px;background:var(--cyan);
          animation:loadpulse 0.8s ease-in-out infinite alternate;
        }
        @keyframes loadpulse{from{height:8px;opacity:0.3}to{height:36px;opacity:1}}
        .loading-text{font-family:var(--mono);font-size:11px;color:var(--muted);letter-spacing:2px;}
        .retry-btn{margin-top:8px;padding:8px 20px;border:1px solid var(--cyan);background:transparent;color:var(--cyan);font-family:var(--mono);font-size:11px;border-radius:3px;cursor:pointer;}

        /* ── Overlay / settings ── */
        .overlay{position:fixed;inset:0;background:rgba(0,0,0,0.75);backdrop-filter:blur(4px);z-index:200;display:flex;justify-content:flex-end;padding:20px;}
        .settings-panel{width:600px;max-height:calc(100vh - 40px);background:var(--s1);border:1px solid var(--border2);border-radius:10px;display:flex;flex-direction:column;overflow:hidden;animation:slideIn .2s ease;}
        @keyframes slideIn{from{transform:translateX(24px);opacity:0}to{transform:none;opacity:1}}
        .sp-header{display:flex;align-items:center;justify-content:space-between;padding:18px 22px;border-bottom:1px solid var(--border);flex-shrink:0;}
        .sp-close{background:none;border:none;color:var(--muted);font-size:16px;cursor:pointer;padding:4px;}
        .sp-close:hover{color:var(--bright);}
        .sp-body{flex:1;overflow-y:auto;padding:20px 22px;display:flex;flex-direction:column;gap:16px;}
        .sp-pat-row{display:flex;flex-direction:column;gap:6px;}
        .sp-label{font-family:var(--mono);font-size:9px;letter-spacing:1px;color:var(--muted);text-transform:uppercase;}
        .sp-input{background:var(--s2);border:1px solid var(--border);border-radius:3px;padding:8px 10px;color:var(--text);font-family:var(--sans);font-size:12px;width:100%;transition:border-color .15s;}
        .sp-input:focus{outline:none;border-color:var(--cyan);}
        .sp-input.sm{font-size:11px;padding:5px 8px;}
        .sp-divider{height:1px;background:var(--border);}
        .sp-cat{display:flex;flex-direction:column;gap:8px;}
        .sp-cat-header{font-family:var(--display);font-size:12px;font-weight:700;color:var(--bright);padding:8px 0 8px 12px;border-left:3px solid;display:flex;align-items:center;gap:10px;}
        .sp-ramadan-badge{font-family:var(--mono);font-size:9px;color:var(--yellow);background:rgba(245,208,32,0.1);padding:2px 8px;border-radius:2px;border:1px solid rgba(245,208,32,0.2);}
        .sp-sig-row{background:var(--s2);border-radius:4px;padding:10px 12px;display:flex;flex-direction:column;gap:8px;}
        .sp-sig-name{font-size:11px;color:var(--text);}
        .sp-fields{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;}
        .sp-field-group{display:flex;flex-direction:column;gap:4px;}
        .sp-field-label{font-family:var(--mono);font-size:8px;letter-spacing:1px;color:var(--muted);text-transform:uppercase;}
        .sp-footer{padding:14px 22px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:flex-end;gap:10px;flex-shrink:0;}
        .sp-msg{font-size:11px;flex:1;}
        .sp-msg.ok{color:var(--cyan);}
        .sp-msg.err{color:var(--pink);}
        .sp-cancel{font-family:var(--mono);font-size:10px;padding:8px 16px;border:1px solid var(--border);background:transparent;color:var(--muted);border-radius:3px;cursor:pointer;}
        .sp-save{font-family:var(--mono);font-size:10px;padding:8px 18px;border:1px solid var(--cyan);background:rgba(0,229,200,0.08);color:var(--cyan);border-radius:3px;cursor:pointer;transition:all .15s;}
        .sp-save:hover:not(:disabled){background:rgba(0,229,200,0.15);}
        .sp-save:disabled{opacity:0.4;cursor:not-allowed;}

        /* ── Footer ── */
        .footer{text-align:center;padding:16px 0 32px;font-family:var(--mono);font-size:9px;color:var(--muted);letter-spacing:2px;}

        /* ── Responsive ── */
        @media(max-width:1100px){.dp-body{grid-template-columns:1fr;}.dp-chart-panel{border-top:1px solid var(--border);}.analysis-grid{grid-template-columns:1fr;}}
        @media(max-width:900px){.topics-grid{grid-template-columns:1fr 1fr;}.cat-grid{grid-template-columns:repeat(2,1fr);}}
        @media(max-width:600px){.topics-grid{grid-template-columns:1fr;}.cat-grid{grid-template-columns:1fr;}.main{padding:16px;}.hdr{padding:12px 16px;}}
      `}</style>

      {/* Header */}
      <header className="hdr">
        <div className="hdr-left">
          <div className="pulse-ring"/>
          <div>
            <div className="hdr-title">Crisis Pulse</div>
            <div className="hdr-sub">Media & Search Intelligence · MENA</div>
          </div>
        </div>
        <div className="hdr-right">
          <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
            {["wikipedia","google_rss","newsapi","guardian","twitch"].map(s=>(
              <span key={s} className={`chip ${sources.includes(s)?"live":"dead"}`}>
                {s.replace("_"," ")}
              </span>
            ))}
          </div>
          <span className="ts">{timeAgoStr}</span>
          <button className="sp-trigger" onClick={()=>setShowSettings(true)}>⚙ Signals</button>
        </div>
      </header>

      {/* Ramadan banner */}
      {isRamadan && <RamadanBanner endDate={ramadanEnd}/>}

      {/* Market tabs */}
      <div className="market-bar">
        {Object.entries(MARKET_FLAGS).map(([m,flag])=>(
          <button key={m} className={`mkt-tab ${activeMarket===m?"active":""}`}
            onClick={()=>setActiveMarket(m)}>
            {flag} {m}
          </button>
        ))}
      </div>

      <main className="main">

        {/* ── Category overview ── */}
        <div>
          <div className="sec">Signal Categories · {activeMarket} · click to drill down</div>
          <div className="cat-grid">
            {catKeys.map(ck=>(
              <CategoryCard key={ck} catKey={ck} cat={categories[ck]}
                signals={flatSigs} markets={markets}
                activeMarket={activeMarket}
                isActive={activeCat===ck}
                onClick={()=>setActiveCat(activeCat===ck?null:ck)}
                newsapi={newsapi} guardian={guardian} rss={rss} />
            ))}
          </div>
        </div>

        {/* ── Signal detail (expandable) ── */}
        {activeCat && activeCatObj && (
          <div className="detail-panel">
            <div className="dp-header" style={{borderTop:`2px solid ${activeCatObj.color}`}}>
              <div>
                <div className="dp-title">{activeCatObj.icon} {activeCatObj.label}</div>
                <div className="dp-hypothesis">{activeCatObj.hypothesis}</div>
              </div>
              <button onClick={()=>setActiveCat(null)}
                style={{background:"none",border:"1px solid var(--border)",color:"var(--muted)",borderRadius:3,padding:"5px 12px",cursor:"pointer",fontFamily:"var(--mono)",fontSize:10}}>
                ✕ Close
              </button>
            </div>
            <div className="dp-body">
              <div className="dp-signals">
                <div style={{display:"flex",gap:20,marginBottom:12,paddingBottom:10,borderBottom:"1px solid var(--border)"}}>
                  <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--muted)",width:160}}>SIGNAL</span>
                  <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--muted)",flex:1}}>7-DAY TREND</span>
                  <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--muted)",width:30,textAlign:"right"}}>IDX</span>
                  <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--muted)",width:40,textAlign:"right"}}>WoW</span>
                  <span style={{fontFamily:"var(--mono)",fontSize:9,color:"var(--muted)",width:55,textAlign:"right"}}>NEWS</span>
                </div>
                {activeSigKeys.map(sk=>(
                  <SignalRow key={sk} sigKey={sk} sig={flatSigs[sk]}
                    markets={markets} activeMarket={activeMarket}
                    dates={dates} newsapi={newsapi} guardian={guardian} />
                ))}
              </div>
              <div className="dp-chart-panel">
                <div style={{fontFamily:"var(--mono)",fontSize:9,letterSpacing:2,color:"var(--muted)",marginBottom:4}}>
                  SIGNAL INDEX · {activeMarket}
                </div>
                <div style={{fontSize:10,color:"var(--muted)",marginBottom:14,fontStyle:"italic"}}>
                  Wikipedia interest, normalised 0–100
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={dates.map((d:string,i:number)=>{
                    const row:any={date:d};
                    activeSigKeys.forEach(sk=>{row[sk]=markets[activeMarket]?.[sk]?.[i]??null;});
                    return row;
                  })}>
                    <XAxis dataKey="date" tick={{fontSize:9,fill:"#3d5060"}} axisLine={false} tickLine={false}/>
                    <YAxis domain={[0,100]} tick={{fontSize:9,fill:"#3d5060"}} axisLine={false} tickLine={false} width={26}/>
                    <Tooltip content={<CustomTooltip/>}/>
                    {activeSigKeys.map(sk=>(
                      <Line key={sk} type="monotone" dataKey={sk} name={flatSigs[sk]?.label}
                        stroke={activeCatObj.color} strokeWidth={1.5}
                        strokeOpacity={0.5+(activeSigKeys.indexOf(sk)*0.5/activeSigKeys.length)}
                        dot={false} connectNulls/>
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        )}

        {/* ── Trending Topics ── */}
        <div>
          <div className="sec">Trending Topics · Google RSS · Today</div>
          <div className="topics-grid">
            {Object.entries(MARKET_FLAGS).map(([market,flag])=>{
              const r=rss[market]||{};
              const sport=r.sport_entertainment_pct||0;
              const crisis=r.crisis_pct||0;
              const other=Math.max(0,100-sport-crisis);
              return (
                <div key={market} className="topic-card">
                  <div className="tc-header">
                    <span className="tc-flag">{flag}</span>
                    <span className="tc-name">{market}</span>
                  </div>
                  <div className="mood-bar">
                    <div style={{width:`${sport}%`,background:"var(--cyan)",borderRadius:2}}/>
                    <div style={{width:`${crisis}%`,background:"var(--pink)",borderRadius:2}}/>
                    <div style={{width:`${other}%`,background:"var(--border)",borderRadius:2}}/>
                  </div>
                  <div className="mood-labels">
                    <span style={{color:"var(--cyan)"}}>◈ Sport/Ent {sport}%</span>
                    <span style={{color:"var(--pink)"}}>◈ Crisis {crisis}%</span>
                  </div>
                  {(r.top_topics||[]).slice(0,5).map((t:string,i:number)=>(
                    <div key={i} className="topic-item">
                      <span className="topic-num">{i+1}</span>{t}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>

        {/* ── Radar + Long-term ── */}
        <div className="analysis-grid">
          <div className="card">
            <div className="card-title">Category Radar · {activeMarket}</div>
            <div className="card-sub">Signal strength by category · latest values</div>
            <ResponsiveContainer width="100%" height={260}>
              <RadarChart data={radarData} margin={{top:10,right:20,bottom:10,left:20}}>
                <PolarGrid stroke="var(--border)" />
                <PolarAngleAxis dataKey="category"
                  tick={{fill:"var(--muted)",fontSize:9,fontFamily:"DM Mono"}} />
                <Radar dataKey="value" stroke="var(--cyan)" fill="var(--cyan)"
                  fillOpacity={0.15} strokeWidth={1.5} dot={{r:3,fill:"var(--cyan)"}}/>
                <Tooltip content={<CustomTooltip/>}/>
              </RadarChart>
            </ResponsiveContainer>
          </div>

          <div className="card">
            <div className="card-title">Long-term Category Trends</div>
            <div className="card-sub">Daily avg signal index per category · all markets</div>
            {history.length > 0 ? (
              <>
                <div className="period-btns">
                  {[14,30,60,90].map(d=>(
                    history.length>=d &&
                    <button key={d} className={`period-btn ${historyDays===d?"active":""}`}
                      onClick={()=>setHistoryDays(d)}>{d}d</button>
                  ))}
                </div>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={historyChart}>
                    <XAxis dataKey="date" tick={{fontSize:9,fill:"#3d5060"}} axisLine={false} tickLine={false} interval="preserveStartEnd"/>
                    <YAxis domain={[0,100]} tick={{fontSize:9,fill:"#3d5060"}} axisLine={false} tickLine={false} width={26}/>
                    <Tooltip content={<CustomTooltip/>}/>
                    {catKeys.map(ck=>(
                      <Line key={ck} type="monotone" dataKey={ck}
                        name={categories[ck].label.split("&")[0].trim()}
                        stroke={categories[ck].color} strokeWidth={1.5}
                        dot={false} connectNulls/>
                    ))}
                  </LineChart>
                </ResponsiveContainer>
                <div style={{display:"flex",flexWrap:"wrap",gap:"6px 16px",marginTop:12}}>
                  {catKeys.map(ck=>(
                    <div key={ck} style={{display:"flex",alignItems:"center",gap:5,fontSize:9,color:"var(--muted)",fontFamily:"var(--mono)"}}>
                      <div style={{width:16,height:2,background:categories[ck].color,borderRadius:1}}/>
                      {categories[ck].label.split("&")[0].trim()}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:200,flexDirection:"column",gap:8}}>
                <div style={{fontSize:24}}>📭</div>
                <div style={{fontFamily:"var(--mono)",fontSize:11,color:"var(--muted)"}}>
                  History builds after first collector run
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Twitch ── */}
        {twitch.total_viewers > 0 && (
          <div>
            <div className="sec">Live Gaming · Twitch · Right Now</div>
            <div className="card">
              <div className="twitch-row">
                <div className="twitch-stat">
                  <div className="twitch-num">{fmt(twitch.total_viewers||0)}</div>
                  <div className="twitch-lbl">Live Viewers</div>
                </div>
                <div className="game-rows">
                  {(twitch.top_games||[]).map((g:any,i:number)=>{
                    const max=(twitch.top_games?.[0]?.viewers)||1;
                    const colors=["var(--cyan)","var(--purple)","var(--orange)","var(--green)","var(--muted)"];
                    return (
                      <div key={i} className="game-row">
                        <div className="game-name">{g.name}</div>
                        <div className="game-bar-bg">
                          <div className="game-bar-fg" style={{width:`${(g.viewers/max)*100}%`,background:colors[i]}}/>
                        </div>
                        <div className="game-views">{fmt(g.viewers)}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="footer">
          CRISIS PULSE · GROUPM MENA · REFRESHED DAILY 09:00 GST · {history.length} DAYS OF HISTORY
        </div>
      </main>

      {showSettings && (
        <SettingsPanel config={config} onClose={()=>setShowSettings(false)} onSave={saveConfig}/>
      )}
    </>
  );
}