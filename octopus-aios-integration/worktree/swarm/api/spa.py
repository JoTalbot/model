"""
swarm/api/spa.py — v2 (Octopus Control Plane)
──────────────────────────────────────────────
Полноценный SPA: Дашборд, События, Процессы (анимация), Ноды, Топология,
Файлообменник (Google-Drive-style), Заметки, Задачи, Чат, Граф памяти
(Obsidian-style), Память (типизация), LLM.
"""
from __future__ import annotations


def build_spa() -> str:
    return _HTML


_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🐙 Octopus · Control Plane</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0d14;--bg2:#10141d;--bg3:#171c28;--bg4:#1f2533;
  --border:#252b3a;--border2:#323a4f;
  --accent:#7dd3fc;--accent2:#a78bfa;--accent3:#f472b6;
  --green:#4ade80;--yellow:#fbbf24;--red:#f87171;--orange:#fb923c;--blue:#60a5fa;
  --text:#e2e8f0;--muted:#64748b;--muted2:#94a3b8;--card:#131826;
  --font:'Inter',system-ui,sans-serif;
  --mono:'JetBrains Mono','Fira Code',monospace;
  --radius:10px;--shadow:0 4px 24px #0008;
}
html{height:100%}
body{background:var(--bg);color:var(--text);font-family:var(--font);
  min-height:100vh;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}
#app{display:flex;flex:1;overflow:hidden;height:100vh}

/* ── NAV ─────────────────────────────────────────── */
nav{width:230px;min-width:230px;background:var(--bg2);
  border-right:1px solid var(--border);display:flex;flex-direction:column;
  padding:0;overflow-y:auto;transition:width .25s}
.nav-logo{padding:18px 20px 14px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:10px}
.nav-logo-text{font-size:15px;font-weight:700;color:var(--accent);letter-spacing:.3px}
.nav-logo-sub{font-size:10px;color:var(--muted);margin-top:1px}
.nav-section{padding:14px 12px 4px;font-size:10px;text-transform:uppercase;
  letter-spacing:1.5px;color:var(--muted);font-weight:600}
.nav-item{display:flex;align-items:center;gap:10px;padding:9px 16px;cursor:pointer;
  border-radius:8px;margin:1px 8px;color:var(--muted);font-size:13.5px;
  transition:all .15s;text-decoration:none;white-space:nowrap}
.nav-item:hover{background:var(--bg3);color:var(--text)}
.nav-item.active{background:linear-gradient(135deg,#1e293b,#0f172a);
  color:var(--accent);border:1px solid #334155}
.nav-item svg{flex-shrink:0;opacity:.7}
.nav-item.active svg{opacity:1}
.nav-badge{margin-left:auto;background:var(--accent2);color:#fff;
  font-size:10px;padding:1px 7px;border-radius:99px;font-weight:600}
.nav-footer{margin-top:auto;padding:12px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)}
.node-dot{display:inline-block;width:7px;height:7px;border-radius:50%;
  background:var(--green);margin-right:5px;box-shadow:0 0 6px var(--green);
  animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}

main{flex:1;overflow-y:auto;padding:24px 28px;background:var(--bg)}
@media(max-width:900px){nav{width:60px;min-width:60px}
  .nav-logo-text,.nav-logo-sub,.nav-section,.nav-item span,.nav-badge,.nav-footer{display:none}
  main{padding:14px}}

/* ── PAGE ─────────────────────────────────────────── */
.page{display:none}.page.active{display:block;animation:fadeIn .2s}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.page-title{font-size:22px;font-weight:700;margin-bottom:4px;display:flex;align-items:center;gap:10px}
.page-sub{font-size:13px;color:var(--muted);margin-bottom:20px}
.row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.spacer{flex:1}

.grid{display:grid;gap:14px}
.grid-4{grid-template-columns:repeat(4,1fr)}
.grid-3{grid-template-columns:repeat(3,1fr)}
.grid-2{grid-template-columns:repeat(2,1fr)}
@media(max-width:1200px){.grid-4{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){.grid-4,.grid-3,.grid-2{grid-template-columns:1fr}}

.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px}
.card-tight{padding:12px}
.card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:10px}
.card-title{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);font-weight:600}
.stat-val{font-size:30px;font-weight:800;line-height:1;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat-sub{font-size:11px;color:var(--muted);margin-top:6px}
.kpi{display:flex;align-items:baseline;gap:8px}

.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border-radius:99px;font-size:11px;font-weight:600}
.badge-green{background:#052e16;color:var(--green);border:1px solid #14532d}
.badge-yellow{background:#1c1100;color:var(--yellow);border:1px solid #713f12}
.badge-red{background:#1c0000;color:var(--red);border:1px solid #7f1d1d}
.badge-blue{background:#0c1a2e;color:var(--accent);border:1px solid #1e3a5f}
.badge-purple{background:#13091f;color:var(--accent2);border:1px solid #3b0764}
.badge-gray{background:#1e293b;color:var(--muted2);border:1px solid #334155}

.table-wrap{overflow:auto;border-radius:var(--radius);border:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{padding:10px 14px;text-align:left;font-size:11px;text-transform:uppercase;
  letter-spacing:.8px;color:var(--muted);background:var(--bg3);
  font-weight:600;border-bottom:1px solid var(--border);position:sticky;top:0;z-index:1}
td{padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#ffffff06}
.mono{font-family:var(--mono);font-size:12px}

.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:8px;
  font-size:13px;font-weight:600;cursor:pointer;border:none;transition:all .15s;font-family:var(--font)}
.btn-primary{background:var(--accent);color:#0c1a2e}
.btn-primary:hover{background:#bae6fd;box-shadow:0 0 12px #7dd3fc55}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}
.btn-ghost:hover{color:var(--text);border-color:var(--accent)}
.btn-red{background:#7f1d1d;color:#fff}
.btn-red:hover{background:#991b1b}
.btn-sm{padding:5px 10px;font-size:12px}
.btn-icon{padding:6px;border-radius:6px;background:transparent;color:var(--muted);border:none;cursor:pointer}
.btn-icon:hover{color:var(--accent);background:var(--bg3)}
input,textarea,select{background:var(--bg3);border:1px solid var(--border);color:var(--text);
  padding:9px 12px;border-radius:8px;font-size:13px;width:100%;outline:none;
  transition:border .15s;font-family:var(--font)}
input:focus,textarea:focus,select:focus{border-color:var(--accent)}
label{font-size:12px;color:var(--muted);display:block;margin-bottom:5px}
.form-group{margin-bottom:12px}
.form-row{display:flex;gap:10px}.form-row>*{flex:1}

/* ── Event log ─────────────────────────────────────── */
#event-log{height:380px;overflow-y:auto;background:var(--bg3);border-radius:8px;
  padding:12px;font-size:12px;font-family:var(--mono);border:1px solid var(--border)}
.ev{padding:3px 0;border-bottom:1px solid #ffffff08;display:flex;gap:8px}
.ev:last-child{border:none}
.ev-time{color:var(--muted);flex-shrink:0;width:80px}
.ev-type{flex-shrink:0;padding:0 6px;border-radius:4px;font-size:10px;font-weight:700;text-transform:uppercase}
.ev-msg{color:var(--text);opacity:.85;flex:1;word-break:break-all}
.ev-node{color:var(--accent)}.ev-gossip{color:var(--accent2)}
.ev-task{color:var(--yellow)}.ev-err{color:var(--red)}.ev-ok{color:var(--green)}

/* ── Spinner / Empty ───────────────────────────────── */
.spinner{width:24px;height:24px;border:3px solid var(--border);
  border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;margin:32px auto}
@keyframes spin{to{transform:rotate(360deg)}}
.empty{text-align:center;padding:36px 18px;color:var(--muted);font-size:14px}

/* ── Toast ─────────────────────────────────────────── */
#toasts{position:fixed;bottom:24px;right:24px;z-index:9999;display:flex;flex-direction:column;gap:8px}
.toast{padding:10px 18px;border-radius:8px;font-size:13px;font-weight:500;
  background:var(--card);border:1px solid var(--border);box-shadow:var(--shadow);
  max-width:340px;animation:slideIn .2s ease}
.toast-ok{border-color:var(--green);color:var(--green)}
.toast-err{border-color:var(--red);color:var(--red)}
@keyframes slideIn{from{transform:translateX(40px);opacity:0}to{transform:none;opacity:1}}

/* ── Progress / bars ───────────────────────────────── */
.progress{height:6px;background:var(--bg3);border-radius:99px;overflow:hidden}
.progress-fill{height:100%;border-radius:99px;transition:width .4s;
  background:linear-gradient(90deg,var(--accent),var(--accent2))}

::-webkit-scrollbar{width:7px;height:7px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:#475569}

/* ── FILE EXPLORER ─────────────────────────────────── */
.fx{display:grid;grid-template-columns:240px 1fr;gap:14px;height:calc(100vh - 180px);min-height:520px}
.fx-side{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  padding:12px;overflow-y:auto}
.fx-side-h{font-size:11px;text-transform:uppercase;color:var(--muted);
  letter-spacing:1px;margin:6px 0 8px;padding:0 6px;font-weight:600;display:flex;justify-content:space-between}
.fx-tree-item{display:flex;align-items:center;gap:6px;padding:6px 8px;border-radius:6px;
  cursor:pointer;font-size:13px;color:var(--text);transition:all .12s}
.fx-tree-item:hover{background:var(--bg3)}
.fx-tree-item.active{background:linear-gradient(90deg,#0c1a2e,transparent);color:var(--accent);border-left:2px solid var(--accent)}
.fx-tree-item-count{margin-left:auto;font-size:10px;color:var(--muted);
  background:var(--bg3);padding:1px 6px;border-radius:8px}
.fx-tree-item.active .fx-tree-item-count{background:#1e3a5f;color:var(--accent)}

.fx-main{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
  display:flex;flex-direction:column;overflow:hidden}
.fx-toolbar{padding:10px 14px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.fx-bread{font-size:13px;color:var(--muted);flex:1;font-family:var(--mono)}
.fx-bread span{color:var(--text)}
.fx-bread a{color:var(--accent);text-decoration:none;cursor:pointer}
.fx-bread a:hover{text-decoration:underline}
.fx-list{flex:1;overflow-y:auto;padding:8px}
.fx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:10px;padding:8px}
.fx-tile{background:var(--bg3);border:1px solid transparent;border-radius:10px;padding:14px 10px;
  text-align:center;cursor:pointer;transition:all .15s;position:relative;overflow:hidden}
.fx-tile:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 6px 18px #0006}
.fx-tile.selected{border-color:var(--accent2);background:#1e1535}
.fx-tile-ico{font-size:38px;margin-bottom:6px;display:block;line-height:1}
.fx-tile-name{font-size:12px;color:var(--text);word-break:break-all;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.fx-tile-size{font-size:10px;color:var(--muted);margin-top:4px}
.fx-tile-ocr{font-size:9px;color:var(--accent);margin-top:4px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;opacity:.85}
mark.ocr-hl{background:#facc15;color:#000;border-radius:2px;padding:0 1px}

.fx-table tr{cursor:pointer}
.fx-table .ico{font-size:18px;width:24px;display:inline-block}

.fx-drop{position:fixed;inset:0;background:#7dd3fc22;border:3px dashed var(--accent);
  z-index:9998;display:flex;align-items:center;justify-content:center;
  font-size:22px;color:var(--accent);font-weight:700;pointer-events:none}

/* ── Modal preview ──────────────────────────────────── */
.modal-bg{position:fixed;inset:0;background:#000a;z-index:9000;
  display:flex;align-items:center;justify-content:center;padding:24px}
.modal{background:var(--card);border:1px solid var(--border2);border-radius:12px;
  max-width:760px;width:100%;max-height:90vh;display:flex;flex-direction:column;overflow:hidden}
.modal-head{padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
.modal-body{padding:18px;overflow:auto;flex:1}
.modal-body pre{font-family:var(--mono);font-size:12.5px;color:var(--accent);
  white-space:pre-wrap;word-break:break-word}

/* ── GRAPH ─────────────────────────────────────────── */
#graph-canvas{width:100%;height:calc(100vh - 220px);min-height:520px;
  background:#080a10;border-radius:var(--radius);border:1px solid var(--border);cursor:grab;display:block}
#graph-canvas:active{cursor:grabbing}
.graph-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-top:10px}
.graph-legend span{display:flex;align-items:center;gap:5px}
.graph-legend i{width:10px;height:10px;border-radius:50%;display:inline-block}

/* ── PROCESSES ─────────────────────────────────────── */
.proc-pipeline{display:flex;align-items:stretch;gap:0;overflow-x:auto;padding:8px 0}
.proc-stage{flex:0 0 180px;background:var(--bg3);border:1px solid var(--border);
  border-radius:10px;padding:12px;margin-right:24px;position:relative}
.proc-stage::after{content:"→";position:absolute;right:-22px;top:50%;transform:translateY(-50%);
  font-size:22px;color:var(--border2)}
.proc-stage:last-child::after{display:none}
.proc-stage-h{font-size:11px;text-transform:uppercase;color:var(--muted);letter-spacing:1px;margin-bottom:8px}
.proc-stage-v{font-size:20px;font-weight:700;color:var(--accent)}
.proc-stage-s{font-size:11px;color:var(--muted);margin-top:4px}
.proc-stage.active{border-color:var(--green);box-shadow:0 0 12px #4ade8033}
.proc-stage.warn{border-color:var(--yellow)}
.proc-stage.err{border-color:var(--red)}
.proc-dot{position:absolute;width:8px;height:8px;border-radius:50%;background:var(--green);
  box-shadow:0 0 8px var(--green);animation:pulse 1.5s infinite;top:8px;right:8px}

.proc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}
.proc-tile{background:var(--bg3);border-radius:8px;padding:12px;border-left:3px solid var(--border2);
  transition:all .2s}
.proc-tile.k-gossip{border-left-color:var(--accent2)}
.proc-tile.k-kademlia{border-left-color:var(--blue)}
.proc-tile.k-rpc{border-left-color:var(--green)}
.proc-tile.k-task{border-left-color:var(--yellow)}
.proc-tile.k-sync{border-left-color:var(--orange)}
.proc-tile.k-awareness{border-left-color:var(--accent3)}
.proc-tile.k-stream{border-left-color:var(--accent)}
.proc-tile-n{font-size:12px;color:var(--text);font-family:var(--mono);word-break:break-all;line-height:1.4}
.proc-tile-c{font-size:18px;font-weight:700;color:var(--accent);margin-top:6px}

/* ── Chat bubble ────────────────────────────────────── */
.chat-msg{display:flex;gap:8px;align-items:flex-start}
.chat-msg.user{flex-direction:row-reverse}
.chat-bubble{max-width:75%;padding:10px 14px;border-radius:12px;font-size:13px;
  line-height:1.6;white-space:pre-wrap;word-break:break-word}
.chat-msg.user .chat-bubble{background:var(--accent);color:#0c1a2e;border-bottom-right-radius:4px}
.chat-msg.agent .chat-bubble{background:var(--bg3);border:1px solid var(--border);border-bottom-left-radius:4px}

/* ── Note card ──────────────────────────────────────── */
.note-card{background:var(--bg3);border:1px solid var(--border);border-radius:var(--radius);
  padding:14px;margin-bottom:10px;transition:border .15s;cursor:pointer}
.note-card:hover{border-color:var(--accent2)}
.note-title{font-weight:600;font-size:14px;margin-bottom:6px}
.note-body{font-size:13px;color:var(--muted2);line-height:1.6;
  white-space:pre-wrap;word-break:break-word;max-height:120px;overflow:hidden}
.note-meta{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap;align-items:center}
.note-tag{font-size:10px;padding:2px 8px;border-radius:99px;background:#0c1a2e;
  color:var(--accent);border:1px solid #1e3a5f;cursor:pointer}

</style>
</head>
<body>
<div id="app">

<!-- ══════════════════ NAV ══════════════════════════════════════════════ -->
<nav>
  <div class="nav-logo">
    <span style="font-size:24px">🐙</span>
    <div>
      <div class="nav-logo-text">Octopus</div>
      <div class="nav-logo-sub">Control Plane v2</div>
    </div>
  </div>

  <div class="nav-section">Обзор</div>
  <a class="nav-item" onclick="nav('knowledge')" href="#knowledge"><svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2zM22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg><span>База Знаний</span></a>
  <a class="nav-item active" onclick="nav('dashboard')" href="#dashboard">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
    <span>Дашборд</span>
  </a>
  <a class="nav-item" onclick="nav('processes')" href="#processes">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 1v6M12 17v6M4.2 4.2l4.3 4.3M15.5 15.5l4.3 4.3M1 12h6M17 12h6M4.2 19.8l4.3-4.3M15.5 8.5l4.3-4.3"/></svg>
    <span>Процессы</span>
    <span class="nav-badge" id="proc-badge">●</span>
  </a>
  <a class="nav-item" onclick="nav('events')" href="#events">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
    <span>События</span>
    <span class="nav-badge" id="ev-badge">0</span>
  </a>

  <div class="nav-section">Сеть</div>
  <a class="nav-item" onclick="nav('nodes')" href="#nodes">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="M12 8v4M8.5 17l3.5-5M15.5 17l-3.5-5"/></svg>
    <span>Ноды / Пиры</span>
  </a>
    <a class="nav-item" onclick="nav('swarm')" href="#swarm">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><circle cx="5" cy="5" r="2"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 7l3 3M17 7l-3 3M7 17l3-3M17 17l-3-3"/></svg>
    <span>Рой (управление)</span>
  </a>
  <a class="nav-item" onclick="nav('reflect')" href="#reflect">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
    <span>Рефлексия</span>
  </a>
  <a class="nav-item" onclick="nav('network')" href="#network">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 3c-4 5-4 13 0 18M12 3c4 5 4 13 0 18M3 12h18"/></svg>
    <span>Топология</span>
  </a>

  <div class="nav-section">Контент</div>
  <a class="nav-item" href="http://drive.178.105.142.113.sslip.io/" target="_blank" title="Professional S3 Drive">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    <span>Drive (S3)</span>
    <span style="font-size:10px;color:var(--muted);margin-left:auto">↗</span>
  </a>
  <a class="nav-item" onclick="nav('files')" href="#files">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
    <span>Файлы (VFS)</span>
  </a>
  </a>
  <a class="nav-item" onclick="nav('notes')" href="#notes">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
    <span>Заметки</span>
  </a>
  <a class="nav-item" onclick="nav('tasks')" href="#tasks">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>
    <span>Задачи</span>
  </a>
  <a class="nav-item" onclick="nav('chat')" href="#chat">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
    <span>Чат</span>
  </a>

  <div class="nav-section">Память</div>
  <a class="nav-item" onclick="nav('graph')" href="#graph">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="18" r="2.5"/><circle cx="12" cy="12" r="2.5"/><path d="M12 12L6 6M12 12l6-6M12 12L6 18M12 12l6 6"/></svg>
    <span>Граф</span>
  </a>
  <a class="nav-item" onclick="nav('memory')" href="#memory">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>
    <span>Типы / Хранилище</span>
  </a>
  <a class="nav-item" onclick="nav('llm')" href="#llm">
    <svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 6v6l4 2"/><circle cx="19" cy="5" r="3"/></svg>
    <span>LLM</span>
  </a>

  <div class="nav-footer">
    <span class="node-dot"></span>
    <span id="nav-node-id">Подключение…</span>
  </div>
</nav>

<!-- ══════════════════ MAIN ═════════════════════════════════════════════ -->
<main>

<!-- ──── DASHBOARD ────────────────────────────────────────────────────── -->
<div id="page-dashboard" class="page active">
  <div class="page-title">🐙 Дашборд</div>
  <div class="page-sub" id="dash-node-info">Загрузка…</div>

  <div class="grid grid-4" style="margin-bottom:16px">
    <div class="card"><div class="card-head"><span class="card-title">Статус</span><span id="s-health-badge"></span></div>
      <div class="stat-val" id="s-status">—</div><div class="stat-sub" id="s-uptime">uptime —</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Рой</span></div>
      <div class="stat-val" id="s-peers">—</div><div class="stat-sub" id="s-peers-sub">всего пиров</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Задачи</span></div>
      <div class="stat-val" id="s-tasks">—</div><div class="stat-sub" id="s-tasks-sub">в пуле</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Gossip</span></div>
      <div class="stat-val" id="s-gossip">—</div><div class="stat-sub" id="s-gossip-sub">сообщений</div></div>
  </div>

  <div class="grid grid-4" style="margin-bottom:16px">
    <div class="card"><div class="card-head"><span class="card-title">Память · Всего</span></div>
      <div class="stat-val" id="s-mem-total" style="font-size:24px">—</div>
      <div class="stat-sub" id="s-mem-bytes">— bytes</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Файлы (VFS)</span></div>
      <div class="stat-val" id="s-files-count" style="font-size:24px">—</div>
      <div class="stat-sub" id="s-files-size">— bytes</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Auth</span></div>
      <div id="s-auth-line" style="font-size:13px;line-height:1.9;color:var(--muted2)">Загрузка…</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Storage · S3</span></div>
      <div class="stat-val" id="s-s3-status" style="font-size:24px">—</div>
      <div class="stat-sub" id="s-s3-info">octopus-memory</div></div>
  </div>

  <div class="grid grid-2">
    <div class="card">
      <div class="card-head"><span class="card-title">Активность · 7 дней</span>
        <button class="btn btn-ghost btn-sm" onclick="loadDashboard()">↻</button></div>
      <canvas id="dash-timeline" style="width:100%;height:140px"></canvas>
    </div>
    <div class="card">
      <div class="card-head"><span class="card-title">Последние события</span>
        <button class="btn btn-ghost btn-sm" onclick="nav('events')">Все →</button></div>
      <div id="dash-events" style="font-size:12px;font-family:var(--mono);max-height:160px;overflow-y:auto"></div>
    </div>
  </div>
</div>

<!-- ──── PROCESSES ────────────────────────────────────────────────────── -->
<!-- ──── KNOWLEDGE GRAPH (Semantic Wiki) ────────────────────────────────── -->
<div id=page-knowledge class=page>
  <div class=page-title>🧠 Граф Знаний (Wiki)</div>
  <div class=page-sub>Визуализация семантических связей между заметками Obsidian и логами опыта.</div>
  <div class=row style=margin-bottom:10px>
    <button class=btn btn-ghost btn-sm onclick="loadKnowledgeGraph()">↻ Обновить</button>
    <div class="spacer"></div>
    <span class="badge badge-blue" id="know-stats">0 узлов · 0 связей</span>
  </div>
  <div style="height:600px;background:var(--bg2);border-radius:12px;position:relative;overflow:hidden;border:1px solid var(--bg3)">
    <canvas id="know-canvas" style="width:100%;height:100%"></canvas>
  </div>
  <div id="know-info" style="margin-top:10px;padding:12px;background:var(--bg3);border-radius:8px;font-size:13px;color:var(--fg2)">
    Наведите на узел, чтобы увидеть связи.
  </div>
</div>

<div id="page-processes" class="page">
  <div class="page-title">⚙️ Процессы</div>
  <div class="page-sub" id="proc-sub">Жизненный цикл узла в реальном времени</div>

  <div class="card" style="margin-bottom:14px">
    <div class="card-head"><span class="card-title">Жизненный цикл</span>
      <span id="proc-tick" class="badge badge-green">● live</span></div>
    <div class="proc-pipeline" id="proc-pipeline"></div>
  </div>

  <div class="grid grid-2" style="margin-bottom:14px">
    <div class="card">
      <div class="card-head"><span class="card-title">Health / Load</span></div>
      <div id="proc-load" style="font-size:13px;line-height:1.9"></div>
    </div>
    <div class="card">
      <div class="card-head"><span class="card-title">Очереди</span></div>
      <div id="proc-queues" style="font-size:13px;line-height:1.9"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><span class="card-title">Активные процессы (asyncio)</span>
      <span class="badge badge-blue" id="proc-count">0</span></div>
    <div class="proc-grid" id="proc-grid"></div>
  </div>
</div>

<!-- ──── EVENTS ────────────────────────────────────────────────────────── -->
<div id="page-events" class="page">
  <div class="page-title">⚡ События</div>
  <div class="page-sub">Живой поток событий ноды (SSE)</div>
  <div class="card">
    <div class="card-head">
      <span class="card-title">Лог</span>
      <div class="row" style="gap:8px">
        <select id="ev-filter" style="width:auto;min-width:140px" onchange="renderFilteredEvents()">
          <option value="">Все типы</option>
        </select>
        <button class="btn btn-ghost btn-sm" onclick="clearLog()">Очистить</button>
        <span id="sse-status" class="badge badge-yellow">Подключение…</span>
      </div>
    </div>
    <div id="event-log"></div>
  </div>
</div>

<!-- ──── NODES ─────────────────────────────────────────────────────────── -->
<div id="page-nodes" class="page">
  <div class="page-title">🌐 Ноды и пиры</div>
  <div class="page-sub">Kademlia DHT + верифицированные handshake-пиры</div>
  <div class="row" style="margin-bottom:14px">
    <button class="btn btn-primary" onclick="loadNodes()">↻ Обновить</button>
    <button class="btn btn-ghost" onclick="nav('network')">Топология →</button>
    <button class="btn btn-ghost" onclick="nav('graph')">Граф →</button>
  </div>

  <div class="grid grid-2" style="margin-bottom:16px">
    <div class="card">
      <div class="card-head"><span class="card-title">Kademlia DHT</span></div>
      <div id="kad-peers-list"><div class="spinner"></div></div>
    </div>
    <div class="card">
      <div class="card-head"><span class="card-title">Handshake (Ed25519)</span></div>
      <div id="hs-peers-list"><div class="spinner"></div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-head"><span class="card-title">Инициировать Handshake</span></div>
    <div class="form-row">
      <div class="form-group"><label>Host</label><input id="hs-host" placeholder="127.0.0.1"></div>
      <div class="form-group"><label>RPC Port</label><input id="hs-port" placeholder="10002" type="number"></div>
    </div>
    <button class="btn btn-primary" onclick="doHandshake()">🤝 Handshake</button>
    <div id="hs-result" style="margin-top:10px;font-size:13px;color:var(--muted)"></div>
  </div>
</div>

<!-- ──── NETWORK TOPOLOGY ──────────────────────────────────────────────── -->
<div id="page-network" class="page">
  <div class="page-title">🕸 Топология</div>
  <div class="page-sub">Визуализация P2P-связей · радиальный layout</div>
  <div class="card">
    <canvas id="topo-canvas" style="width:100%;height:480px;background:#080a10;border-radius:8px"></canvas>
    <div class="graph-legend">
      <span><i style="background:#7dd3fc"></i>Текущая нода</span>
      <span><i style="background:#a78bfa"></i>Kademlia</span>
      <span><i style="background:#4ade80"></i>Handshake (verified)</span>
      <span><i style="background:#fbbf24"></i>Swarm awareness</span>
    </div>
  </div>
</div>

<!-- ──── FILES ─────────────────────────────────────────────────────────── -->
<div id="page-files" class="page">
  <div class="page-title">📁 Файлы</div>
  <div class="page-sub">Распределённое хранилище VFS · drag&drop · поиск · теги</div>

  <div class="row" style="margin-bottom:12px">
    <input type="file" id="fx-input" multiple style="display:none" onchange="uploadFiles(this.files)">
    <button class="btn btn-primary" onclick="document.getElementById('fx-input').click()">⬆️ Загрузить</button>
    <button class="btn btn-ghost" onclick="mkdirPrompt()">📂 Новая папка</button>
    <button class="btn btn-ghost" onclick="migratePayload()" title="Восстановить payload для старых файлов">🔧 Миграция</button>
    <button class="btn btn-ghost btn-sm" onclick="setFxView('grid')" id="fx-view-grid">▦ Плитка</button>
    <button class="btn btn-ghost btn-sm" onclick="setFxView('list')" id="fx-view-list">≡ Список</button>
    <div class="spacer"></div>
    <input id="fx-search" placeholder="🔍 Поиск по имени / содержимому / OCR-тексту…" style="max-width:280px"
           onkeydown="if(event.key==='Enter')loadFiles()">
    <button class="btn btn-ghost btn-sm" onclick="loadFiles()">↻</button>
  </div>

  <div class="fx">
    <aside class="fx-side">
      <div class="fx-side-h">Папки <button class="btn-icon" onclick="loadFilesTree()" title="Обновить">↻</button></div>
      <div id="fx-tree"><div class="spinner"></div></div>
      <div class="fx-side-h" style="margin-top:16px">Сводка</div>
      <div id="fx-stats" style="font-size:12px;color:var(--muted2);line-height:1.9;padding:0 8px"></div>
    </aside>
    <section class="fx-main">
      <div class="fx-toolbar">
        <div class="fx-bread" id="fx-bread">/</div>
        <span class="badge badge-blue" id="fx-count">0</span>
      </div>
      <div class="fx-list" id="fx-list"><div class="spinner"></div></div>
    </section>
  </div>
</div>

<!-- ──── NOTES ─────────────────────────────────────────────────────────── -->
<div id="page-notes" class="page">
  <div class="page-title">📝 Заметки</div>
  <div class="page-sub">Локальная память · Markdown + теги</div>

  <div class="card" style="margin-bottom:16px">
    <div class="card-head"><span class="card-title">Добавить</span></div>
    <div class="form-group"><label>Заголовок</label><input id="note-title" placeholder="Заголовок"></div>
    <div class="form-group"><label>Содержимое</label><textarea id="note-body" rows="3" placeholder="Текст (поддерживается [[wiki-link]] и #tag)"></textarea></div>
    <div class="form-group"><label>Теги (csv)</label><input id="note-tags" placeholder="clients, orders"></div>
    <div class="row">
      <button class="btn btn-primary" onclick="addNote()">💾 Сохранить</button>
      <button class="btn btn-ghost" onclick="loadNotes()">↻</button>
    </div>
  </div>

  <div class="card" style="margin-bottom:14px">
    <div class="form-row">
      <input id="note-search" placeholder="Поиск по заметкам…">
      <button class="btn btn-primary" style="flex:0 0 auto" onclick="searchNotes()">🔍</button>
    </div>
    <div id="search-results" style="margin-top:12px"></div>
  </div>

  <div id="notes-list"><div class="spinner"></div></div>
</div>

<!-- ──── TASKS ────────────────────────────────────────────────────────── -->
<div id="page-tasks" class="page">
  <div class="page-title">✅ Задачи</div>
  <div class="page-sub">Distributed Task Pool</div>
  <div class="card" style="margin-bottom:16px">
    <div class="form-group"><label>Новая задача</label>
      <textarea id="task-desc" rows="2" placeholder="Что нужно сделать…"></textarea></div>
    <button class="btn btn-primary" onclick="submitTask()">🚀 В рой</button>
  </div>
  <div class="card">
    <div class="card-head"><span class="card-title">Список</span>
      <button class="btn btn-ghost btn-sm" onclick="loadTasks()">↻</button></div>
    <div id="tasks-list"><div class="spinner"></div></div>
  </div>
</div>

<!-- ──── CHAT ─────────────────────────────────────────────────────────── -->
<div id="page-chat" class="page">
  <div class="page-title">💬 Чат с агентом</div>
  <div class="page-sub">RAG по локальным данным</div>
  <div class="card" style="margin-bottom:14px">
    <div id="chat-messages" style="min-height:340px;max-height:520px;overflow-y:auto;
         display:flex;flex-direction:column;gap:10px;padding:4px">
      <div class="empty">Задай вопрос — агент ответит на основе памяти</div>
    </div>
  </div>
  <div class="form-row" style="align-items:flex-end">
    <input id="chat-input" placeholder="Вопрос агенту…" onkeydown="if(event.key==='Enter')sendChat()">
    <button class="btn btn-primary" onclick="sendChat()" style="flex:0 0 auto;height:40px">➤</button>
  </div>
  <div id="chat-thinking" style="display:none;font-size:12px;color:var(--muted);margin-top:8px">
    <div class="spinner" style="width:14px;height:14px;border-width:2px;margin:0;display:inline-block;vertical-align:middle"></div>
    &nbsp;Думаю…
  </div>
</div>

<!-- ──── GRAPH (Obsidian-style) ────────────────────────────────────────── -->
<div id="page-graph" class="page">
  <div class="page-title">🕷 Граф памяти</div>
  <div class="page-sub">Узлы: <b>файлы · заметки · теги · задачи · ноды · таблицы</b> · сила-направленный layout</div>
  <div class="row" style="margin-bottom:10px">
    <select id="gr-scope" onchange="loadGraph()" style="width:auto">
      <option value="all">Всё</option>
      <option value="memory">Только память</option>
      <option value="swarm">Только рой</option>
    </select>
    <select id="gr-max" onchange="loadGraph()" style="width:auto">
      <option value="100">≤100 узлов</option>
      <option value="250" selected>≤250</option>
      <option value="500">≤500</option>
      <option value="1000">≤1000</option>
    </select>
    <input id="gr-search" placeholder="🔍 Подсветить (label содержит…)" oninput="graphHighlight(this.value)" style="max-width:260px">
    <button class="btn btn-ghost btn-sm" onclick="loadGraph()">↻ Перестроить</button>
    <button class="btn btn-ghost btn-sm" onclick="graphResetView()">⤢ Центрировать</button>
    <div class="spacer"></div>
    <span class="badge badge-blue" id="gr-stats">0 узлов · 0 рёбер</span>
  </div>
  <canvas id="graph-canvas"></canvas>
  <div id="graph-empty" style="display:none;text-align:center;padding:20px;color:var(--muted)">
    Нажми <b>↻ Перестроить</b>, чтобы построить граф из текущей памяти.
  </div>
  <div class="graph-legend">
    <span><i style="background:#7dd3fc"></i>node_self</span>
    <span><i style="background:#4ade80"></i>node verified</span>
    <span><i style="background:#a78bfa"></i>node / kad</span>
    <span><i style="background:#fbbf24"></i>task</span>
    <span><i style="background:#60a5fa"></i>file</span>
    <span><i style="background:#f472b6"></i>note</span>
    <span><i style="background:#fb923c"></i>tag</span>
    <span><i style="background:#94a3b8"></i>table</span>
    <span style="color:var(--muted);margin-left:auto">мышь: pan · колесо: zoom · клик узел: фокус</span>
  </div>
</div>

<!-- ──── MEMORY TYPES ──────────────────────────────────────────────────── -->
<div id="page-memory" class="page">
  <div class="page-title">🗄 Память · Типизация</div>
  <div class="page-sub">Что и сколько хранится в памяти узла</div>
  <div class="grid grid-3" id="mem-kpi" style="margin-bottom:14px"><div class="spinner"></div></div>
  <div class="grid grid-2" style="margin-bottom:14px">
    <div class="card"><div class="card-head"><span class="card-title">По типу (kind)</span></div>
      <div id="mem-kinds"></div></div>
    <div class="card"><div class="card-head"><span class="card-title">Топ теги</span></div>
      <div id="mem-tags"></div></div>
  </div>
  <div class="card" style="margin-bottom:14px">
    <div class="card-head"><span class="card-title">Таблицы памяти</span></div>
    <div id="mem-tables"></div>
  </div>
  <div class="card">
    <div class="card-head"><span class="card-title">Последние записи</span>
      <button class="btn btn-ghost btn-sm" onclick="loadMemory()">↻</button></div>
    <div id="mem-records"><div class="spinner"></div></div>
  </div>
</div>

<!-- ──── LLM ──────────────────────────────────────────────────────────── -->
<div id="page-llm" class="page">
  <div class="page-title">🤖 LLM</div>
  <div class="page-sub">Использование моделей</div>
  <div class="card">
    <div class="card-head"><span class="card-title">Статистика</span>
      <button class="btn btn-ghost btn-sm" onclick="loadLLM()">↻</button></div>
    <div id="llm-stats"><div class="spinner"></div></div>
  </div>
</div>


<!-- ──── SWARM management ──────────────────────────────────────────────── -->
<div id="page-swarm" class="page">
  <div class="page-title">🐙 Рой · управление</div>
  <div class="page-sub">Узлы Docker · spawn / kill / статус</div>
  <div class="card" style="margin-bottom:14px">
    <div class="card-head"><span class="card-title">Создать новый узел</span></div>
    <div class="form-row">
      <div class="form-group"><label>Имя (опц.)</label><input id="sp-name" placeholder="octopus-child-8300"></div>
      <div class="form-group"><label>Порт (опц.)</label><input id="sp-port" placeholder="8300" type="number"></div>
      <div class="form-group"><label>Bootstrap</label><input id="sp-boot" value="127.0.0.1:8000"></div>
    </div>
    <button class="btn btn-primary" onclick="doSpawn()">🌱 Породить</button>
    <div id="sp-result" style="margin-top:10px;font-size:13px;color:var(--muted)"></div>
  </div>
  <div class="card">
    <div class="card-head"><span class="card-title">Активные ноды</span>
      <button class="btn btn-ghost btn-sm" onclick="loadSwarmNodes()">↻</button></div>
    <div id="sw-nodes-list"><div class="spinner"></div></div>
  </div>
</div>

<!-- ──── REFLECT ───────────────────────────────────────────────────────── -->
<div id="page-reflect" class="page">
  <div class="page-title">🔮 Саморефлексия</div>
  <div class="page-sub">Что агент знает о себе и своей истории</div>
  <div class="card">
    <div class="card-head"><span class="card-title">Insights</span>
      <button class="btn btn-primary btn-sm" onclick="loadReflect()">↻ Запустить анализ</button></div>
    <div id="reflect-out"><div class="empty">Нажми «Запустить анализ»</div></div>
  </div>
</div>

</main><!-- /main -->
</div><!-- /app -->

<div id="toasts"></div>
<div id="modal-host"></div>
<div id="fx-drop-overlay" class="fx-drop" style="display:none">↓ Отпусти, чтобы загрузить</div>

<script>
/* ═══════════════════════════════════════════════════════════════════════
   Core
   ═══════════════════════════════════════════════════════════════════════ */
const API = '';
let evCount = 0;
let evBuffer = [];       // все события для фильтрации
let sse = null;

function nav(page){
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  const pg = document.getElementById('page-'+page);
  if(pg) pg.classList.add('active');
  document.querySelectorAll('.nav-item').forEach(i=>{
    if((i.getAttribute('onclick')||'').includes("'"+page+"'")) i.classList.add('active');
  });
  location.hash = page;
  const loaders = {
    nodes: loadNodes, notes: loadNotes, tasks: loadTasks,
    memory: loadMemory, llm: loadLLM, network: drawTopo,
    files: ()=>{loadFilesTree(); loadFiles(); loadFilesStats();},
    swarm: loadSwarmNodes, reflect: loadReflect,
    graph: loadGraph, processes: loadProcesses, events: ()=>{}
  };
  if(loaders[page]) loaders[page]();
}

function toast(msg, ok=true){
  const el = document.createElement('div');
  el.className = 'toast '+(ok?'toast-ok':'toast-err');
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(()=>el.remove(), 3500);
}

async function api(path, opts={}){
  try{
    const r = await fetch(API+path, opts);
    const ct = r.headers.get('content-type')||'';
    if(ct.includes('application/json')) return await r.json();
    return await r.text();
  }catch(e){ return {error:e.message}; }
}
async function apiPost(path, body){
  return api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
}

function escHtml(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
let fxSearchTerm = '';
function hlEsc(text, term){
  const safe = escHtml(text);
  if(!term) return safe;
  const t = String(term).trim();
  if(!t) return safe;
  const esc = t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  try{
    return safe.replace(new RegExp('('+esc+')','gi'), '<mark class="ocr-hl">$1</mark>');
  }catch(e){ return safe; }
}
function fmtBytes(n){
  if(!n) return '0 B';
  const u=['B','KB','MB','GB','TB']; let i=0; let x=n;
  while(x>=1024 && i<u.length-1){x/=1024;i++;}
  return x.toFixed(x<10?1:0)+' '+u[i];
}
function fmtTs(ts){
  if(!ts) return '—';
  const d = new Date(ts*1000);
  return d.toLocaleString('ru');
}
function fmtUptime(s){
  if(!s) return '—';
  s=Math.floor(s);
  const d=Math.floor(s/86400); s-=d*86400;
  const h=Math.floor(s/3600); s-=h*3600;
  const m=Math.floor(s/60);
  return (d?d+'д ':'')+(h?h+'ч ':'')+m+'м';
}

/* ═══════════════════════════════════════════════════════════════════════
   Dashboard
   ═══════════════════════════════════════════════════════════════════════ */
async function loadDashboard(){
  // показываем что грузим
  ['s-status','s-peers','s-tasks','s-gossip','s-mem-total','s-files-count'].forEach(id=>{
    const el=document.getElementById(id); if(el && el.textContent==='—') el.textContent='…';
  });
  const [info, peers, tasks, gossip, mtypes, fstats, tline, swNodes] = await Promise.all([
    api('/api/v1/node/info'),
    api('/api/v1/network/peers'),
    api('/api/v1/tasks'),
    api('/api/v1/network/gossip'),
    api('/api/v1/memory/types'),
    api('/api/v1/files/stats'),
    api('/api/v1/memory/timeline?days=7'),
    api('/api/v1/swarm/nodes'),
  ]);
  const nid = info?.node_id || '—';
  document.getElementById('nav-node-id').textContent = nid.slice(0,12)+'…';
  const swCount = (swNodes?.nodes||[]).filter(n=>n.running).length;
  document.getElementById('dash-node-info').innerHTML =
    `<span class="mono">Node ID:</span> <span class="mono" style="color:var(--accent)">${escHtml(nid)}</span> · порт ${info?.port||'?'} · <b style="color:var(--green)">${swCount}</b> узлов роя`;

  const ok = !info?.error;
  document.getElementById('s-status').textContent = ok?'✓ Online':'✗ Off';
  document.getElementById('s-status').style.color = ok ? 'var(--green)' : 'var(--red)';
  document.getElementById('s-status').style.background = 'none';
  document.getElementById('s-status').style.webkitTextFillColor = ok ? 'var(--green)' : 'var(--red)';
  const hb = document.getElementById('s-health-badge');
  if(hb) hb.innerHTML = ok ? '<span class="badge badge-green">live</span>' : '<span class="badge badge-red">down</span>';
  document.getElementById('s-uptime').textContent = ok ? 'auth: ' + (info?.auth?.hmac_enabled?'HMAC':'none') : '';
  const peerN = peers?.peers?.length ?? 0;
  document.getElementById('s-peers').textContent = peerN;
  document.getElementById('s-peers').style.color = peerN ? '' : 'var(--muted)';
  document.getElementById('s-peers-sub').textContent = `+ ${swCount} docker-нод`;
  const tN = tasks?.tasks?.length ?? 0;
  document.getElementById('s-tasks').textContent = tN;
  document.getElementById('s-tasks').style.color = tN ? '' : 'var(--muted)';
  document.getElementById('s-gossip').textContent = (gossip?.total_received ?? gossip?.messages?.length ?? 0);
  document.getElementById('s-gossip-sub').textContent = `всего сообщений: ${(gossip?.messages?.length || gossip?.total_received || 0)}`;

  
  // Fetch S3 status from public status API
  const swStat = await api('/api/swarm-status');
  if(swStat && Array.isArray(swStat)) {
      const gS3 = swStat.find(s => s.name === 'Garage S3');
      if(gS3) {
          const el = document.getElementById('s-s3-status');
          el.textContent = gS3.status_ru === 'онлайн' ? '✓ Online' : '✗ Off';
          el.style.color = gS3.st === 'online' ? 'var(--green)' : 'var(--red)';
          document.getElementById('s-s3-info').textContent = gS3.host + ' · ' + gS3.info;
      }
  }

  
  // Fetch S3 status from public status API
  try {
      const swStat = await api('/api/swarm-status');
      if(swStat && Array.isArray(swStat)) {
          const gS3 = swStat.find(s => s.name === 'Garage S3');
          if(gS3) {
              const el = document.getElementById('s-s3-status');
              if(el) {
                  el.textContent = gS3.status_ru === 'онлайн' ? '✓ Online' : '✗ Off';
                  el.style.color = gS3.st === 'online' ? 'var(--green)' : 'var(--red)';
                  document.getElementById('s-s3-info').textContent = gS3.host + ' · ' + gS3.info;
              }
          }
      }
  } catch(e) { console.error(S3 status fetch error, e); }

  // Memory + Files KPI
  document.getElementById('s-mem-total').textContent = mtypes?.total_records ?? 0;
  document.getElementById('s-mem-bytes').textContent = fmtBytes(mtypes?.total_bytes||0);
  document.getElementById('s-files-count').textContent = fstats?.files_total ?? 0;
  document.getElementById('s-files-size').textContent = fmtBytes(fstats?.bytes_total||0);

  // Auth
  const a = info?.auth||{};
  document.getElementById('s-auth-line').innerHTML = `
    <div>🔐 HMAC: <b style="color:${a.hmac_enabled?'var(--green)':'var(--muted)'}">${a.hmac_enabled?'on':'off'}</b></div>
    <div>🔑 Ed25519: <b style="color:${a.ed25519?'var(--green)':'var(--muted)'}">${a.ed25519?'on':'off'}</b></div>
    <div>🤝 Verified peers: <b style="color:var(--accent)">${a.verified_peers??0}</b></div>
    <div class="mono" style="font-size:11px;color:var(--accent2)">${(a.pubkey||'').slice(0,24)}…</div>`;

  // Timeline mini chart
  drawTimeline(tline?.timeline||[]);
  // Recent events
  const evHtml = evBuffer.slice(-6).reverse().map(e=>{
    return `<div class="ev"><span class="ev-time">${e.time}</span><span class="ev-type ${e.cls}">${escHtml(e.type)}</span><span class="ev-msg">${escHtml(e.msg)}</span></div>`;
  }).join('') || '<div style="color:var(--muted)">пока тихо…</div>';
  document.getElementById('dash-events').innerHTML = evHtml;
}

function drawTimeline(arr){
  const empty = !arr.length || arr.every(d=>!d.total);
  if(empty){
    const c = document.getElementById('dash-timeline');
    if(c){
      const W=c.offsetWidth||400, H=140;
      c.width=W; c.height=H;
      const ctx=c.getContext('2d'); ctx.clearRect(0,0,W,H);
      ctx.fillStyle='#64748b'; ctx.font='13px sans-serif'; ctx.textAlign='center';
      ctx.fillText('— нет активности за 7 дней —', W/2, H/2);
    }
    return;
  }
  const c = document.getElementById('dash-timeline');
  if(!c||!arr.length) return;
  const dpr = window.devicePixelRatio||1;
  const W = c.offsetWidth, H = c.offsetHeight||140;
  c.width = W*dpr; c.height = H*dpr;
  const ctx = c.getContext('2d'); ctx.scale(dpr,dpr); ctx.clearRect(0,0,W,H);
  const maxV = Math.max(1, ...arr.map(d=>d.total));
  const bw = W/arr.length;
  arr.forEach((d,i)=>{
    const h = (d.total/maxV)*(H-40);
    const g = ctx.createLinearGradient(0,H-30-h,0,H-30);
    g.addColorStop(0,'#7dd3fc'); g.addColorStop(1,'#a78bfa');
    ctx.fillStyle = g;
    ctx.fillRect(i*bw+4, H-30-h, bw-8, h);
    ctx.fillStyle = '#64748b'; ctx.font = '10px sans-serif'; ctx.textAlign='center';
    ctx.fillText(d.day.slice(5), i*bw+bw/2, H-12);
    if(d.total){ ctx.fillStyle='#e2e8f0';ctx.fillText(d.total, i*bw+bw/2, H-34-h); }
  });
}

/* ═══════════════════════════════════════════════════════════════════════
   SSE Events
   ═══════════════════════════════════════════════════════════════════════ */
function initSSE(){
  const statusEl = document.getElementById('sse-status');
  try{
    sse = new EventSource(API+'/api/v1/events/stream');
    sse.onopen = ()=>{ statusEl.textContent='● Live'; statusEl.className='badge badge-green'; };
    sse.onmessage = (e)=>{
      let d; try{d=JSON.parse(e.data);}catch{d={type:'raw',message:e.data};}
      evCount++;
      document.getElementById('ev-badge').textContent = evCount;
      const type = d.type||d.event||'event';
      const cls = type.includes('node')?'ev-node':
        type.includes('gossip')?'ev-gossip':
        type.includes('task')?'ev-task':
        type.includes('error')?'ev-err':'ev-ok';
      const msg = d.message||d.node_id||d.msg_id||JSON.stringify(d).slice(0,120);
      const time = new Date().toLocaleTimeString('ru');
      const item = {type, cls, msg, time, raw:d};
      evBuffer.push(item);
      if(evBuffer.length>500) evBuffer.shift();
      // обновим фильтр-селект
      const sel = document.getElementById('ev-filter');
      if(sel && ![...sel.options].some(o=>o.value===type)){
        const opt = document.createElement('option'); opt.value=type; opt.textContent=type;
        sel.appendChild(opt);
      }
      renderFilteredEvents();
    };
    sse.onerror = ()=>{ statusEl.textContent='✗ Нет связи'; statusEl.className='badge badge-red'; };
  }catch(e){ statusEl.textContent='✗ SSE'; statusEl.className='badge badge-red'; }
}
function renderFilteredEvents(){
  const log = document.getElementById('event-log');
  if(!log) return;
  const filter = document.getElementById('ev-filter')?.value || '';
  const items = filter ? evBuffer.filter(i=>i.type===filter) : evBuffer;
  log.innerHTML = items.slice(-200).reverse().map(e=>{
    return `<div class="ev"><span class="ev-time">${e.time}</span><span class="ev-type ${e.cls}">${escHtml(e.type)}</span><span class="ev-msg">${escHtml(e.msg)}</span></div>`;
  }).join('') || '<div class="empty">пока пусто…</div>';
}
function clearLog(){ evBuffer=[]; evCount=0; document.getElementById('ev-badge').textContent='0'; renderFilteredEvents(); }

/* ═══════════════════════════════════════════════════════════════════════
   Processes (pipeline + asyncio tasks)
   ═══════════════════════════════════════════════════════════════════════ */
let _procTimer = null;
async function loadProcesses(){
  if(_procTimer) clearInterval(_procTimer);
  document.getElementById('proc-pipeline').innerHTML = '<div class="spinner"></div>';
  await refreshProc();
  _procTimer = setInterval(refreshProc, 4000);
}
async function refreshProc(){
  const r = await api('/api/v1/swarm/processes');
  if(r?.error){ document.getElementById('proc-pipeline').innerHTML = '<div class="empty">'+escHtml(r.error)+'</div>'; return; }
  document.getElementById('proc-sub').textContent = `node ${r.node_id||'?'} · uptime ${fmtUptime(r.uptime_sec)} · ${r.health||'?'}`;

  // Pipeline стадии
  const load = r.load||{};
  const gossip = r.gossip||{};
  const queues = r.queues||{};
  const stages = [
    {h:'Health', v:(r.health_score!=null?Math.round(r.health_score*100)+'%':'—'), s:r.health||'?', cls:(r.health==='healthy'?'active': (r.health==='degraded'?'warn':'err'))},
    {h:'Peers (verified)', v:String(r.peers?.verified||0), s:'verified', cls:r.peers?.verified?'active':''},
    {h:'Peers (kad)', v:String(r.peers?.swarm_map||0), s:'swarm map', cls:''},
    {h:'Gossip RX', v:String(gossip.total_received||0), s:'gossip received', cls:'active'},
    {h:'Gossip TX', v:String(gossip.total_sent||0), s:'gossip sent', cls:'active'},
    {h:'Tasks', v:String(queues.tasks_total||0), s:JSON.stringify(queues.tasks||{}).slice(1,-1)||'idle', cls:queues.tasks_total?'active':''},
    {h:'Mem items', v:String(load.memory_items||0), s:'records', cls:''},
  ];
  document.getElementById('proc-pipeline').innerHTML = stages.map(s=>`
    <div class="proc-stage ${s.cls}">
      <div class="proc-dot"></div>
      <div class="proc-stage-h">${escHtml(s.h)}</div>
      <div class="proc-stage-v">${escHtml(s.v)}</div>
      <div class="proc-stage-s">${escHtml(s.s)}</div>
    </div>`).join('');

  // Health/Load card
  document.getElementById('proc-load').innerHTML = `
    <div>Role: <b style="color:var(--accent)">${escHtml(r.role||'?')}</b></div>
    <div>Skills: ${(r.skills||[]).map(s=>`<span class="badge badge-blue">${escHtml(s)}</span>`).join(' ')||'<span style="color:var(--muted)">—</span>'}</div>
    <div>CPU: <b>${(load.cpu_percent||0).toFixed?.(1)||load.cpu_percent||0}%</b> · RAM: <b>${(load.ram_mb||0).toFixed?.(0)||load.ram_mb||0} MB</b></div>
    <div>Tasks: pending=${load.tasks_pending||0} · running=${load.tasks_running||0} · done=${load.tasks_done||0}</div>
    <div>Gossip RX/TX: ${load.gossip_rx||0} / ${load.gossip_tx||0}</div>
  `;
  document.getElementById('proc-queues').innerHTML = `
    <div>Tasks total: <b>${queues.tasks_total||0}</b></div>
    <div>Tasks by status:<br>${
      Object.entries(queues.tasks||{}).map(([k,v])=>`<span class="badge badge-blue" style="margin:2px">${escHtml(k)}: ${v}</span>`).join(' ') || '<span style="color:var(--muted)">— пусто</span>'
    }</div>
    <div style="margin-top:10px">RPC: ${escHtml(JSON.stringify(r.rpc||{}).slice(0,180))}</div>
  `;

  // Active asyncio processes
  const procs = r.processes||[];
  document.getElementById('proc-count').textContent = procs.length;
  document.getElementById('proc-grid').innerHTML = procs.length
    ? procs.map(p=>`
      <div class="proc-tile k-${escHtml(p.kind||'other')}">
        <div class="proc-tile-n">${escHtml(p.name)}</div>
        <div class="proc-tile-c">×${p.count}</div>
      </div>`).join('')
    : '<div class="empty">Нет видимых процессов (HTTP-handler в отдельном потоке)</div>';
}

/* ═══════════════════════════════════════════════════════════════════════
   Nodes & Topology
   ═══════════════════════════════════════════════════════════════════════ */
let topoKad = [], topoHs = [];
async function loadNodes(){
  const [peers, hsPeers] = await Promise.all([
    api('/api/v1/network/peers'),
    api('/api/v1/peer_list').catch(()=>({peers:[]})),
  ]);
  const kadPeers = peers?.peers || [];
  topoKad = kadPeers;
  const kadEl = document.getElementById('kad-peers-list');
  if(!kadPeers.length){
    kadEl.innerHTML = '<div class="empty">Kademlia DHT пуст.<br><small style="color:var(--muted)">Узлы появятся когда их пиры найдут друг друга по UDP.<br>Если у тебя несколько нод роя — это норма в первые секунды.</small></div>';
  } else kadEl.innerHTML = kadPeers.map(p=>`
    <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border)">
      <span style="width:8px;height:8px;border-radius:50%;background:var(--accent2);box-shadow:0 0 6px var(--accent2)"></span>
      <span class="mono" style="font-size:12px">${escHtml(String(p))}</span>
    </div>`).join('');

  const hsList = hsPeers?.peers || [];
  topoHs = hsList;
  const hsEl = document.getElementById('hs-peers-list');
  if(!hsList.length){
    hsEl.innerHTML = '<div class="empty">Нет верифицированных пиров.<br><small style="color:var(--muted)">Введи host:port ниже и нажми Handshake — после успеха пир появится с ✓ Ed25519.</small></div>';
  } else hsEl.innerHTML = hsList.map(p=>`
    <div style="display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid var(--border)">
      <span style="width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green)"></span>
      <div style="flex:1">
        <div class="mono" style="font-size:11px;color:var(--accent)">${escHtml(p.node_id||'?')}</div>
        <div style="font-size:11px;color:var(--muted)">${escHtml(p.address||'')}</div>
      </div>
      <span class="badge badge-green">✓</span>
    </div>`).join('');
}
async function doHandshake(){
  const host = document.getElementById('hs-host').value.trim() || '127.0.0.1';
  const port = parseInt(document.getElementById('hs-port').value)||10002;
  const r = await apiPost('/api/v1/network/handshake', {host, port});
  const el = document.getElementById('hs-result');
  if(r?.ok){ el.innerHTML='<span style="color:var(--green)">✅ OK</span>'; toast('Handshake OK!'); loadNodes(); }
  else { el.innerHTML='<span style="color:var(--red)">✗ '+escHtml(r?.reason||r?.error||'fail')+'</span>'; toast('Handshake fail', false); }
}

function drawTopo(){
  const c = document.getElementById('topo-canvas');
  if(!c) return;
  const dpr = window.devicePixelRatio||1;
  const W=c.offsetWidth, H=c.offsetHeight||480;
  c.width=W*dpr; c.height=H*dpr;
  const ctx=c.getContext('2d'); ctx.scale(dpr,dpr); ctx.clearRect(0,0,W,H);
  const cx=W/2, cy=H/2;
  const all = [...topoKad.map(p=>({label:String(p), color:'#a78bfa'})),
               ...topoHs.map(p=>({label:p.node_id||'?', color:'#4ade80'}))];
  const R = Math.min(W,H)*0.38;
  all.forEach((p,i)=>{
    const angle=(i/Math.max(1,all.length))*Math.PI*2 - Math.PI/2;
    const j = R*0.1*Math.sin(Date.now()/1500+i);
    const tx = cx+(R+j)*Math.cos(angle);
    const ty = cy+(R+j)*Math.sin(angle);
    ctx.beginPath(); ctx.moveTo(cx,cy); ctx.lineTo(tx,ty);
    ctx.strokeStyle = p.color+'55'; ctx.lineWidth=1.4; ctx.setLineDash([4,4]); ctx.stroke(); ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(tx,ty,7,0,Math.PI*2);
    ctx.fillStyle=p.color; ctx.shadowColor=p.color; ctx.shadowBlur=12; ctx.fill(); ctx.shadowBlur=0;
    ctx.fillStyle='#94a3b8'; ctx.font='10px monospace';
    ctx.fillText(p.label.slice(0,16), tx+10, ty+4);
  });
  ctx.beginPath(); ctx.arc(cx,cy,16,0,Math.PI*2);
  ctx.fillStyle='#7dd3fc'; ctx.shadowColor='#7dd3fc'; ctx.shadowBlur=22; ctx.fill(); ctx.shadowBlur=0;
  ctx.fillStyle='#0c1a2e'; ctx.font='bold 11px monospace'; ctx.textAlign='center';
  ctx.fillText('ME', cx, cy+4); ctx.textAlign='left';
  if(!all.length){
    ctx.fillStyle='#64748b'; ctx.font='13px sans-serif'; ctx.textAlign='center';
    ctx.fillText('Нет пиров', cx, cy+40); ctx.textAlign='left';
  }
}
let _topoAnim=null;
function startTopoAnim(){
  if(_topoAnim) cancelAnimationFrame(_topoAnim);
  function loop(){
    if(document.getElementById('page-network').classList.contains('active')) drawTopo();
    _topoAnim = requestAnimationFrame(loop);
  }
  loop();
}

/* ═══════════════════════════════════════════════════════════════════════
   FILES (Google-Drive style)
   ═══════════════════════════════════════════════════════════════════════ */
let fxPath = '/';
let fxView = 'list';
let fxTree = [];

function setFxView(v){
  fxView = v;
  document.getElementById('fx-view-grid').className = 'btn btn-ghost btn-sm';
  document.getElementById('fx-view-list').className = 'btn btn-ghost btn-sm';
  document.getElementById('fx-view-'+v).className = 'btn btn-primary btn-sm';
  loadFiles();
}

async function loadFilesTree(){
  const r = await api('/api/v1/files/tree');
  if(!r?.ok){ document.getElementById('fx-tree').innerHTML = '<div class="empty">'+escHtml(r?.error||'fail')+'</div>'; return; }
  fxTree = r.tree||[];
  renderTree();
}
function renderTree(){
  const el = document.getElementById('fx-tree');
  if(!fxTree.length){ el.innerHTML='<div class="empty">пусто</div>'; return; }
  el.innerHTML = fxTree.map(t=>{
    const depth = Math.max(0, (t.path.match(/\//g)||[]).length - 1);
    const isActive = t.path === fxPath || (t.path==='/' && fxPath==='/');
    return `<div class="fx-tree-item ${isActive?'active':''}" style="padding-left:${8+depth*14}px" onclick="fxNavigate('${escHtml(t.path)}')">
      <span>${t.path==='/'?'🏠':'📁'}</span>
      <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(t.name)}</span>
      <span class="fx-tree-item-count">${t.files_count}</span>
    </div>`;
  }).join('');
}
function fxNavigate(p){
  fxPath = p; renderTree(); loadFiles(); updateBread();
}
function updateBread(){
  const parts = fxPath.split('/').filter(Boolean);
  const html = ['<a onclick="fxNavigate(\'/\')">🏠 /</a>'];
  let cur = '';
  parts.forEach(p=>{
    cur += '/' + p;
    html.push('<a onclick="fxNavigate(\''+cur+'\')">'+escHtml(p)+'</a>');
  });
  document.getElementById('fx-bread').innerHTML = html.join(' <span style="color:var(--muted)">/</span> ');
}

async function loadFiles(){
  const search = document.getElementById('fx-search').value.trim();
  fxSearchTerm = search;
  const qs = new URLSearchParams({path:fxPath, search});
  const r = await api('/api/v1/files/list?'+qs);
  const el = document.getElementById('fx-list');
  if(!r?.ok){ el.innerHTML='<div class="empty">'+escHtml(r?.error||'fail')+'</div>'; return; }
  const files = (r.files||[]).filter(f=>f.name!=='.keep');
  document.getElementById('fx-count').textContent = files.length;
  updateBread();
  if(!files.length){ el.innerHTML='<div class="empty">📂 Пусто. Перетащи файл сюда или нажми «Загрузить».</div>'; return; }
  if(fxView==='grid'){
    el.innerHTML = '<div class="fx-grid">'+files.map(f=>fileTile(f)).join('')+'</div>';
  }else{
    el.innerHTML = `<div class="table-wrap" style="border:none"><table class="fx-table">
      <tr><th></th><th>Имя</th><th>Путь</th><th>Размер</th><th>MIME</th><th>Теги</th><th>Изменён</th><th></th></tr>
      ${files.map(f=>fileRow(f)).join('')}
    </table></div>`;
  }
}
function fileIcon(mime, name){
  const m = mime||'';
  if(m.startsWith('image/')) return '🖼️';
  if(m.startsWith('video/')) return '🎬';
  if(m.startsWith('audio/')) return '🎵';
  if(m.includes('pdf')) return '📕';
  if(m.includes('zip')||m.includes('compressed')) return '🗜️';
  if(m.includes('json')) return '🧾';
  if(m.includes('html')||m.includes('xml')) return '🌐';
  if(m.startsWith('text/')) return '📄';
  if((name||'').endsWith('.py')) return '🐍';
  if((name||'').endsWith('.md')) return '📝';
  return '📦';
}
function ocrBadge(f){
  if(!f.ocr_status) return '';
  if(f.ocr_status==='done') return `<span class="badge badge-green" title="OCR распознан: ${f.ocr_chars||0} симв.">🔤 OCR</span>`;
  if(f.ocr_status==='error') return `<span class="badge badge-red" title="Ошибка OCR">🔤 ошибка</span>`;
  return `<span class="badge" title="OCR в очереди">🔤 …</span>`;
}
function fileTile(f){
  return `<div class="fx-tile" onclick='previewFile(${JSON.stringify(f).replace(/'/g, "&apos;")})'>
    <span class="fx-tile-ico">${fileIcon(f.mime,f.name)}</span>
    <div class="fx-tile-name">${escHtml(f.name)}</div>
    <div class="fx-tile-size">${fmtBytes(f.size)}</div>
    ${f.ocr_status==='done' ? `<div class="fx-tile-ocr" title="${escHtml(f.ocr_text||'')}">🔤 ${hlEsc((f.ocr_text||'').slice(0,40), fxSearchTerm)}</div>` : ''}
  </div>`;
}
function fileRow(f){
  return `<tr onclick='previewFile(${JSON.stringify(f).replace(/'/g, "&apos;")})'>
    <td><span class="ico">${fileIcon(f.mime,f.name)}</span></td>
    <td><b>${escHtml(f.name)}</b></td>
    <td class="mono" style="color:var(--muted)">${escHtml(f.path)}</td>
    <td>${fmtBytes(f.size)}</td>
    <td><span class="badge badge-blue">${escHtml((f.mime||'').split('/')[0]||'?')}</span> ${ocrBadge(f)}</td>
    <td>${(f.tags||[]).filter(t=>t!=='vfs').map(t=>`<span class="note-tag">#${escHtml(t)}</span>`).join(' ')}</td>
    <td style="color:var(--muted);font-size:11px">${fmtTs(f.ts)}</td>
    <td onclick="event.stopPropagation()">
      <button class="btn-icon" title="Скачать" onclick="downloadFile('${escHtml(f.ref)}')">⬇</button>
      <button class="btn-icon" title="Удалить" onclick="deleteFile('${escHtml(f.ref)}')">🗑</button>
    </td>
  </tr>`;
}
async function loadFilesStats(){
  const r = await api('/api/v1/files/stats');
  if(!r?.ok) return;
  document.getElementById('fx-stats').innerHTML = `
    <div>Файлов: <b style="color:var(--accent)">${r.files_total}</b></div>
    <div>Объём: <b>${fmtBytes(r.bytes_total)}</b></div>
    <hr style="border:none;border-top:1px solid var(--border);margin:8px 0">
    <div style="margin-bottom:6px">По типу:</div>
    ${Object.entries(r.by_mime||{}).map(([k,v])=>
      `<div style="display:flex;justify-content:space-between"><span>${escHtml(k)}</span><span>${v.count} · ${fmtBytes(v.size)}</span></div>`
    ).join('') || '<div style="color:var(--muted)">—</div>'}
  `;
}

async function uploadFiles(fileList){
  if(!fileList||!fileList.length) return;
  for(const f of fileList){
    await uploadOne(f);
  }
  loadFiles(); loadFilesTree(); loadFilesStats();
}
function uploadOne(file){
  return new Promise(resolve=>{
    const reader = new FileReader();
    reader.onload = async ()=>{
      const b64 = btoa(String.fromCharCode(...new Uint8Array(reader.result)));
      try{
        const r = await fetch(API+'/api/v1/files/upload', {
          method:'POST',
          headers:{
            'X-File-Name': encodeURIComponent(file.name),
            'X-File-Path': encodeURIComponent(fxPath),
            'X-File-Mime': file.type || 'application/octet-stream',
            'X-Encoding': 'base64',
            'Content-Type': 'application/octet-stream',
          },
          body: b64
        });
        const j = await r.json();
        if(j?.ok) toast('Загружен: '+file.name);
        else toast('Ошибка: '+(j?.error||'fail'), false);
      }catch(e){ toast('Сеть: '+e.message, false); }
      resolve();
    };
    reader.readAsArrayBuffer(file);
  });
}
async function deleteFile(ref){
  if(!confirm('Удалить файл?')) return;
  const r = await apiPost('/api/v1/files/delete', {ref});
  if(r?.ok){ toast('Удалён'); loadFiles(); loadFilesStats(); loadFilesTree(); }
  else toast(r?.error||'fail', false);
}
function downloadFile(ref){
  window.open(API+'/api/v1/files/download?ref='+encodeURIComponent(ref), '_blank');
}
async function mkdirPrompt(){
  const name = prompt('Имя новой папки (внутри '+fxPath+')');
  if(!name) return;
  const path = (fxPath==='/'?'':fxPath) + '/' + name.replace(/^\/+|\/+$/g,'');
  const r = await apiPost('/api/v1/files/mkdir', {path});
  if(r?.ok){ toast('Создана'); loadFilesTree(); fxNavigate(path); }
  else toast(r?.error||'fail', false);
}
function previewFile(f){
  const host = document.getElementById('modal-host');
  const rawUrl = API + '/api/v1/files/raw?ref=' + encodeURIComponent(f.ref);
  let body = '';
  const mime = f.mime || '';
  if(mime.startsWith('image/')){
    body = `<img src="${rawUrl}" style="max-width:100%;max-height:70vh;border-radius:8px;display:block;margin:0 auto">`;
  } else if(mime === 'application/pdf'){
    body = `<iframe src="${rawUrl}" style="width:100%;height:70vh;border:none;border-radius:8px;background:#fff"></iframe>`;
  } else if(mime.startsWith('video/')){
    body = `<video src="${rawUrl}" controls style="max-width:100%;max-height:70vh;border-radius:8px"></video>`;
  } else if(mime.startsWith('audio/')){
    body = `<audio src="${rawUrl}" controls style="width:100%"></audio>`;
  } else if(mime.startsWith('text/') || mime.includes('json') || mime.includes('xml') ||
            f.name.match(/\.(md|py|js|ts|css|html|yaml|yml|sh|conf|cfg|log|sql)$/i)){
    body = `<div style="font-size:12px;color:var(--muted);margin-bottom:6px">Загружаю…</div><pre id="prev-text">…</pre>`;
    setTimeout(async()=>{
      try{
        const r = await fetch(rawUrl);
        const txt = await r.text();
        const el = document.getElementById('prev-text');
        if(el) el.textContent = txt.slice(0, 200000);
      }catch(e){}
    }, 50);
  } else {
    body = `<pre>${escHtml(f.preview||'(нет inline preview · нажми «Скачать»)')}</pre>`;
  }
  host.innerHTML = `<div class="modal-bg" onclick="if(event.target===this)this.remove()">
    <div class="modal" style="max-width:900px">
      <div class="modal-head">
        <span style="font-size:22px">${fileIcon(f.mime, f.name)}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;overflow:hidden;text-overflow:ellipsis">${escHtml(f.name)}</div>
          <div style="font-size:11px;color:var(--muted)" class="mono">${escHtml(f.ref)}</div>
        </div>
        <button class="btn btn-primary btn-sm" onclick="downloadFile('${escHtml(f.ref)}')">⬇ Скачать</button>
        <button class="btn btn-red btn-sm" onclick="if(confirm('Удалить?')){deleteFile('${escHtml(f.ref)}');this.closest('.modal-bg').remove();}">🗑</button>
        <button class="btn-icon" onclick="this.closest('.modal-bg').remove()">✕</button>
      </div>
      <div class="modal-body">
        <div style="margin-bottom:10px;color:var(--muted);font-size:12px">
          Путь: <span class="mono" style="color:var(--text)">${escHtml(f.path)}</span> ·
          MIME: <b>${escHtml(f.mime)}</b> ·
          Размер: <b>${fmtBytes(f.size)}</b> ·
          Изменён: ${fmtTs(f.ts)}
        </div>
        <div style="margin-bottom:10px">
          ${(f.tags||[]).map(t=>`<span class="note-tag">#${escHtml(t)}</span>`).join(' ')}
        </div>
        ${f.ocr_status ? `<details ${f.ocr_status==='done'?'open':''} style="margin-bottom:10px;background:var(--card,#111);border:1px solid var(--border);border-radius:8px;padding:8px 10px">
          <summary style="cursor:pointer;color:var(--accent);font-size:13px;user-select:none">🔤 OCR${f.ocr_status==='done'?` · ${f.ocr_chars||0} симв.`:`: ${escHtml(f.ocr_status)}`}</summary>
          ${f.ocr_text ? `<pre style="margin-top:8px;max-height:240px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.5">${hlEsc(f.ocr_text, fxSearchTerm)}</pre>` : `<div style="margin-top:6px;color:var(--muted);font-size:12px">${f.ocr_status==='error'?'Ошибка распознавания.':'Текст ещё не распознан (ожидает обработки OCR-воркером, до ~5 мин).'}</div>`}
        </details>` : ''}
        ${body}
      </div>
    </div>
  </div>`;
}

// Drag&Drop
function initDragDrop(){
  let dragCt = 0;
  const ov = document.getElementById('fx-drop-overlay');
  window.addEventListener('dragenter', e=>{
    e.preventDefault();
    if(document.getElementById('page-files').classList.contains('active')){
      dragCt++; ov.style.display='flex';
    }
  });
  window.addEventListener('dragover', e=>e.preventDefault());
  window.addEventListener('dragleave', e=>{ dragCt--; if(dragCt<=0){dragCt=0;ov.style.display='none';} });
  window.addEventListener('drop', e=>{
    e.preventDefault();
    dragCt=0; ov.style.display='none';
    if(document.getElementById('page-files').classList.contains('active')){
      uploadFiles(e.dataTransfer.files);
    }
  });
}

/* ═══════════════════════════════════════════════════════════════════════
   NOTES / TASKS / CHAT
   ═══════════════════════════════════════════════════════════════════════ */
async function loadNotes(){
  const r = await api('/api/v1/memory/records?limit=30');
  const el = document.getElementById('notes-list');
  const records = (r?.records||[]).filter(x=>x.table!=='vfs_files');
  if(!records.length){ el.innerHTML='<div class="empty">Нет заметок</div>'; return; }
  el.innerHTML = records.map(noteCard).join('');
}
function noteCard(r){
  const tags = (r.tags||[]).filter(t=>!t.startsWith('table:')).map(t=>`<span class="note-tag">#${escHtml(t)}</span>`).join(' ');
  return `<div class="note-card">
    <div class="note-title">${escHtml(r.title||r.ref||'Заметка')}</div>
    <div class="note-body">${escHtml((r.content||'').slice(0,400))}</div>
    <div class="note-meta">${tags}<span style="color:var(--muted);font-size:11px;margin-left:auto">${fmtTs(r.ts)}</span></div>
  </div>`;
}
async function addNote(){
  const title = document.getElementById('note-title').value.trim();
  const body  = document.getElementById('note-body').value.trim();
  const tags  = document.getElementById('note-tags').value.split(',').map(t=>t.trim()).filter(Boolean);
  if(!body) { toast('Введи текст', false); return; }
  const r = await apiPost('/api/v1/memory/insert', {title, content:body, tags});
  if(r?.ok||r?.ref){ toast('Сохранено'); ['note-title','note-body','note-tags'].forEach(id=>document.getElementById(id).value=''); loadNotes(); }
  else toast(r?.error||'fail', false);
}
async function searchNotes(){
  const q = document.getElementById('note-search').value.trim();
  if(!q) return;
  const r = await api('/api/v1/memory/records?search='+encodeURIComponent(q));
  const el = document.getElementById('search-results');
  const recs = r?.records||[];
  el.innerHTML = recs.length ? recs.map(noteCard).join('') : '<div style="color:var(--muted);font-size:13px">Ничего</div>';
}

async function loadTasks(){
  const r = await api('/api/v1/tasks');
  const el = document.getElementById('tasks-list');
  const tasks = r?.tasks||[];
  if(!tasks.length){ el.innerHTML='<div class="empty">Нет задач</div>'; return; }
  el.innerHTML = `<div class="table-wrap"><table>
    <tr><th>ID</th><th>Статус</th><th>Назначен</th><th>Описание</th></tr>
    ${tasks.map(t=>`<tr>
      <td class="mono" style="font-size:11px">${escHtml((t.id||'').slice(0,12))}…</td>
      <td>${statusBadge(t.status)}</td>
      <td class="mono" style="font-size:11px">${escHtml((t.assigned_to||'—').slice(0,10))}</td>
      <td>${escHtml((t.description||'').slice(0,80))}</td>
    </tr>`).join('')}
  </table></div>`;
}
function statusBadge(s){
  const map={pending:'badge-yellow',claimed:'badge-blue',running:'badge-purple',done:'badge-green',failed:'badge-red'};
  return `<span class="badge ${map[s]||'badge-gray'}">${escHtml(s||'?')}</span>`;
}
async function submitTask(){
  const desc = document.getElementById('task-desc').value.trim();
  if(!desc) { toast('Введи описание', false); return; }
  const r = await apiPost('/api/v1/tasks', {description: desc});
  if(r?.success||r?.task_id){ toast('Отправлена'); document.getElementById('task-desc').value=''; loadTasks(); }
  else toast(r?.reason||r?.error||'fail', false);
}

const chatMsgs = [];
async function sendChat(){
  const q = document.getElementById('chat-input').value.trim();
  if(!q) return;
  document.getElementById('chat-input').value='';
  addChat('user', q);
  document.getElementById('chat-thinking').style.display='block';
  const r = await api('/api/v1/memory/ask?q='+encodeURIComponent(q));
  document.getElementById('chat-thinking').style.display='none';
  addChat('agent', r?.answer || r?.error || JSON.stringify(r));
}
function addChat(role, text){
  const el = document.getElementById('chat-messages');
  const empty = el.querySelector('.empty'); if(empty) empty.remove();
  const div = document.createElement('div'); div.className='chat-msg '+role;
  div.innerHTML = `<div class="chat-bubble">${escHtml(text)}</div>`;
  el.appendChild(div); el.scrollTop = el.scrollHeight;
}

/* ═══════════════════════════════════════════════════════════════════════
   GRAPH (Obsidian-style force layout)
   ═══════════════════════════════════════════════════════════════════════ */
const GR = {
  nodes:[], edges:[], pos:{}, vel:{},
  scale:1, ox:0, oy:0,
  drag:null, hover:null, sel:null,
  highlight:'',
  raf:null,
};
const KIND_COLOR = {
  node_self:'#7dd3fc', node_verified:'#4ade80', node_kad:'#a78bfa', node:'#a78bfa',
  task:'#fbbf24', file:'#60a5fa', note:'#f472b6', wiki:'#ec4899',
  tag:'#fb923c', table:'#94a3b8', record:'#64748b'
};
const KIND_RADIUS = {
  node_self:14, node_verified:10, node_kad:8, node:9, task:7,
  file:6, note:6, wiki:7, tag:5, table:11, record:5
};

async function loadGraph(){
  const eEl=document.getElementById('graph-empty'); if(eEl) eEl.style.display='none';
  const scope = document.getElementById('gr-scope').value;
  const max = document.getElementById('gr-max').value;
  document.getElementById('gr-stats').textContent = 'Загрузка…';
  const r = await api(`/api/v1/memory/graph?scope=${scope}&max_nodes=${max}`);
  if(!r?.ok && !r?.nodes){ document.getElementById('gr-stats').textContent = 'Ошибка'; return; }
  GR.nodes = r.nodes||[]; GR.edges = r.edges||[];
  if(!GR.nodes.length){
    const eEl=document.getElementById('graph-empty');
    if(eEl){eEl.style.display='block'; eEl.innerHTML='🤷 Память пуста — добавь заметку или файл, и нажми ↻';}
  }
  document.getElementById('gr-stats').textContent = `${GR.nodes.length} узлов · ${GR.edges.length} рёбер`;
  // Инициализация позиций
  const c = document.getElementById('graph-canvas');
  const W=c.offsetWidth, H=c.offsetHeight||520;
  GR.pos = {}; GR.vel = {};
  GR.nodes.forEach((n,i)=>{
    const a = (i/GR.nodes.length)*Math.PI*2;
    GR.pos[n.id] = {x: W/2 + Math.cos(a)*Math.min(W,H)*0.35*Math.random(), y: H/2 + Math.sin(a)*Math.min(W,H)*0.35*Math.random()};
    GR.vel[n.id] = {x:0, y:0};
  });
  if(!GR.raf) graphLoop();
}
function graphLoop(){
  graphTick();
  graphDraw();
  GR.raf = requestAnimationFrame(graphLoop);
}
function graphTick(){
  const c = document.getElementById('graph-canvas');
  if(!c) return;
  const W=c.offsetWidth, H=c.offsetHeight||520;
  // Repulsion
  const k_rep = 1500;
  const ids = GR.nodes.map(n=>n.id);
  for(let i=0;i<ids.length;i++){
    const a = GR.pos[ids[i]]; if(!a) continue;
    for(let j=i+1;j<ids.length;j++){
      const b = GR.pos[ids[j]]; if(!b) continue;
      let dx = a.x-b.x, dy = a.y-b.y;
      let d2 = dx*dx+dy*dy; if(d2<1) d2=1;
      const f = k_rep/d2;
      const d = Math.sqrt(d2);
      const fx = (dx/d)*f, fy = (dy/d)*f;
      GR.vel[ids[i]].x += fx; GR.vel[ids[i]].y += fy;
      GR.vel[ids[j]].x -= fx; GR.vel[ids[j]].y -= fy;
    }
  }
  // Spring (edges)
  GR.edges.forEach(e=>{
    const a = GR.pos[e.src], b = GR.pos[e.dst]; if(!a||!b) return;
    const dx = b.x-a.x, dy=b.y-a.y;
    const d = Math.sqrt(dx*dx+dy*dy)||1;
    const target = 80 / (e.weight||1);
    const f = (d-target)*0.02;
    const fx = (dx/d)*f, fy=(dy/d)*f;
    GR.vel[e.src].x += fx; GR.vel[e.src].y += fy;
    GR.vel[e.dst].x -= fx; GR.vel[e.dst].y -= fy;
  });
  // Gravity to center + damping + integrate
  const cx=W/2, cy=H/2;
  GR.nodes.forEach(n=>{
    const p = GR.pos[n.id], v = GR.vel[n.id]; if(!p) return;
    v.x += (cx-p.x)*0.001; v.y += (cy-p.y)*0.001;
    v.x *= 0.82; v.y *= 0.82;
    if(GR.drag && GR.drag.id===n.id){ p.x = GR.drag.x; p.y = GR.drag.y; v.x=0; v.y=0; return; }
    p.x += v.x; p.y += v.y;
  });
}
function graphDraw(){
  const c = document.getElementById('graph-canvas'); if(!c) return;
  const dpr = window.devicePixelRatio||1;
  const W=c.offsetWidth, H=c.offsetHeight||520;
  if(c.width!==W*dpr||c.height!==H*dpr){c.width=W*dpr;c.height=H*dpr;}
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,W,H);
  // pan/zoom
  ctx.translate(GR.ox, GR.oy); ctx.scale(GR.scale, GR.scale);
  // edges
  ctx.lineWidth = 1;
  GR.edges.forEach(e=>{
    const a = GR.pos[e.src], b = GR.pos[e.dst]; if(!a||!b) return;
    const hl = GR.highlight && (matchHL(GR.nodes.find(n=>n.id===e.src))||matchHL(GR.nodes.find(n=>n.id===e.dst)));
    const focus = GR.sel && (e.src===GR.sel||e.dst===GR.sel);
    ctx.strokeStyle = focus ? '#7dd3fcaa' : (hl ? '#a78bfa88' : '#2a2a3855');
    ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke();
  });
  // nodes
  GR.nodes.forEach(n=>{
    const p = GR.pos[n.id]; if(!p) return;
    const r = KIND_RADIUS[n.kind]||6;
    const col = KIND_COLOR[n.kind]||'#64748b';
    const hl = matchHL(n);
    const focus = GR.sel === n.id;
    ctx.beginPath(); ctx.arc(p.x,p.y,r,0,Math.PI*2);
    ctx.fillStyle = focus ? '#fff' : col;
    if(hl||focus){ ctx.shadowColor = col; ctx.shadowBlur = 14; }
    ctx.fill(); ctx.shadowBlur = 0;
    // label
    if(r>=7 || GR.scale>1.3 || hl || focus){
      ctx.fillStyle = focus ? '#fff' : (hl ? '#fff' : '#94a3b8');
      ctx.font = (r>=10?'bold ':'')+'11px '+(n.kind==='tag'?'sans-serif':'monospace');
      ctx.fillText((n.label||'').slice(0,24), p.x+r+3, p.y+4);
    }
  });
}
function matchHL(n){
  if(!GR.highlight||!n) return false;
  return (n.label||'').toLowerCase().includes(GR.highlight.toLowerCase()) ||
         (n.kind||'').toLowerCase().includes(GR.highlight.toLowerCase());
}
function graphHighlight(v){ GR.highlight = v||''; }
function graphResetView(){ GR.scale=1; GR.ox=0; GR.oy=0; }

// Mouse events
function initGraphMouse(){
  const c = document.getElementById('graph-canvas'); if(!c) return;
  function toGraph(x,y){
    const rect = c.getBoundingClientRect();
    return {x: ((x-rect.left)-GR.ox)/GR.scale, y: ((y-rect.top)-GR.oy)/GR.scale};
  }
  function hit(p){
    for(let i=GR.nodes.length-1;i>=0;i--){
      const n = GR.nodes[i]; const pos = GR.pos[n.id]; if(!pos) continue;
      const r = KIND_RADIUS[n.kind]||6;
      const dx=p.x-pos.x, dy=p.y-pos.y;
      if(dx*dx+dy*dy <= (r+3)*(r+3)) return n;
    }
    return null;
  }
  let panning=false, panLast=null;
  c.addEventListener('mousedown', e=>{
    const p = toGraph(e.clientX, e.clientY);
    const n = hit(p);
    if(n){ GR.drag = {id:n.id, x:p.x, y:p.y}; GR.sel = n.id; }
    else { panning=true; panLast={x:e.clientX, y:e.clientY}; }
  });
  c.addEventListener('mousemove', e=>{
    const p = toGraph(e.clientX, e.clientY);
    if(GR.drag){ GR.drag.x=p.x; GR.drag.y=p.y; return; }
    if(panning){ GR.ox += e.clientX-panLast.x; GR.oy += e.clientY-panLast.y; panLast={x:e.clientX,y:e.clientY}; return; }
    GR.hover = hit(p);
    c.style.cursor = GR.hover ? 'pointer':'grab';
  });
  window.addEventListener('mouseup', ()=>{ GR.drag=null; panning=false; });
  c.addEventListener('wheel', e=>{
    e.preventDefault();
    const f = e.deltaY < 0 ? 1.1 : 0.9;
    GR.scale = Math.max(0.2, Math.min(4, GR.scale*f));
  }, {passive:false});
  c.addEventListener('click', e=>{
    const p = toGraph(e.clientX, e.clientY);
    const n = hit(p);
    if(n){ GR.sel = n.id; toast(`${n.kind} · ${n.label}`); }
  });
}

/* ═══════════════════════════════════════════════════════════════════════
   MEMORY types
   ═══════════════════════════════════════════════════════════════════════ */
async function loadMemory(){
  const [types, recs] = await Promise.all([
    api('/api/v1/memory/types'),
    api('/api/v1/memory/records?limit=20'),
  ]);
  const kpi = document.getElementById('mem-kpi');
  if(!types?.ok){ kpi.innerHTML='<div class="card"><div class="empty">'+escHtml(types?.error||'fail')+'</div></div>'; return; }
  kpi.innerHTML = `
    <div class="card"><div class="card-head"><span class="card-title">Записей</span></div>
      <div class="stat-val">${types.total_records}</div><div class="stat-sub">всего в памяти</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Объём</span></div>
      <div class="stat-val" style="font-size:24px">${fmtBytes(types.total_bytes||0)}</div><div class="stat-sub">${Object.keys(types.by_mime||{}).length} mime-типов</div></div>
    <div class="card"><div class="card-head"><span class="card-title">Период</span></div>
      <div style="font-size:13px;color:var(--muted2);line-height:1.7">
        <div>с: ${fmtTs(types.ts_min)}</div>
        <div>по: ${fmtTs(types.ts_max)}</div>
      </div></div>
  `;
  const totalKind = Object.values(types.by_kind||{}).reduce((a,b)=>a+b,0)||1;
  document.getElementById('mem-kinds').innerHTML = Object.entries(types.by_kind||{}).sort((a,b)=>b[1]-a[1]).map(([k,v])=>{
    const col = KIND_COLOR[k]||'#64748b';
    return `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:13px;margin-bottom:3px">
        <span style="color:${col}">● ${escHtml(k)}</span><b>${v}</b></div>
      <div class="progress"><div class="progress-fill" style="width:${(v/totalKind)*100}%;background:${col}"></div></div>
    </div>`;
  }).join('');
  document.getElementById('mem-tags').innerHTML = (types.top_tags||[]).slice(0,20).map(t=>
    `<span class="note-tag" style="margin:2px">#${escHtml(t.tag)} · ${t.count}</span>`
  ).join(' ') || '<div style="color:var(--muted)">пусто</div>';
  document.getElementById('mem-tables').innerHTML = `<div class="table-wrap"><table>
    <tr><th>Таблица</th><th>Записей</th><th>Kind</th><th>Объём</th></tr>
    ${(types.types||[]).map(t=>`<tr>
      <td class="mono">${escHtml(t.table)}</td>
      <td>${t.count}</td>
      <td><span class="badge badge-blue">${escHtml(t.kind)}</span></td>
      <td>${fmtBytes(t.size||0)}</td>
    </tr>`).join('')}
  </table></div>`;

  const records = recs?.records||[];
  document.getElementById('mem-records').innerHTML = !records.length ? '<div class="empty">пусто</div>' : `<div class="table-wrap"><table>
    <tr><th>Ref</th><th>Table</th><th>Заголовок</th><th>Mime</th><th>Теги</th><th>Время</th></tr>
    ${records.map(r=>`<tr>
      <td class="mono" style="font-size:11px">${escHtml((r.ref||'').slice(0,16))}</td>
      <td><span class="badge badge-gray">${escHtml(r.table||'?')}</span></td>
      <td>${escHtml(r.title||r.content?.slice(0,40)||r.ref||'—')}</td>
      <td><span class="badge badge-blue">${escHtml((r.mime||'').split('/')[0]||'?')}</span></td>
      <td>${(r.tags||[]).filter(t=>!t.startsWith('table:')).slice(0,5).map(t=>`<span class="note-tag">#${escHtml(t)}</span>`).join(' ')}</td>
      <td style="color:var(--muted);font-size:11px">${fmtTs(r.ts)}</td>
    </tr>`).join('')}
  </table></div>`;
}

/* ═══════════════════════════════════════════════════════════════════════
   LLM
   ═══════════════════════════════════════════════════════════════════════ */
async function loadLLM(){
  const r = await api('/api/v1/llm/usage');
  const el = document.getElementById('llm-stats');
  if(r?.error||!r){ el.innerHTML='<div class="empty">LLM-статистика недоступна</div>'; return; }
  const models = r.models||[];
  el.innerHTML = `
    <div style="margin-bottom:14px">
      <div style="font-size:12px;color:var(--muted);margin-bottom:4px">Всего вызовов</div>
      <div class="stat-val" style="font-size:28px">${r.total_calls ?? '—'}</div>
    </div>
    ${models.length?`<div class="table-wrap"><table>
      <tr><th>Модель</th><th>Вызовов</th><th>Токенов</th><th>Ошибок</th></tr>
      ${models.map(m=>`<tr>
        <td class="mono" style="font-size:11px">${escHtml(m.model)}</td>
        <td>${m.calls??'—'}</td><td>${m.tokens??'—'}</td><td>${m.errors??0}</td>
      </tr>`).join('')}
    </table></div>`:'<div class="empty">Нет данных</div>'}
  `;
}



/* ═══════════════════════════════════════════════════════════════════════
   SWARM management
   ═══════════════════════════════════════════════════════════════════════ */
async function loadSwarmNodes(){
  const r = await api('/api/v1/swarm/nodes');
  const el = document.getElementById('sw-nodes-list');
  if(!r?.ok){ el.innerHTML='<div class="empty">'+escHtml(r?.error||'fail')+'</div>'; return; }
  const nodes = r.nodes||[];
  if(!nodes.length){ el.innerHTML='<div class="empty">🤷 Нет узлов. Нажми «🌱 Породить» выше.</div>'; return; }
  el.innerHTML = `<div class="table-wrap"><table>
    <tr><th>●</th><th>Имя</th><th>Порт</th><th>Image</th><th>Статус</th><th>Uptime</th><th></th></tr>
    ${nodes.map(n=>`<tr>
      <td>${n.is_self?'<span class="badge badge-blue">SELF</span>':(n.running?'<span style="color:var(--green)">●</span>':'<span style="color:var(--red)">●</span>')}</td>
      <td><b>${escHtml(n.name)}</b></td>
      <td class="mono">${n.port||'?'}</td>
      <td class="mono" style="font-size:11px;color:var(--muted)">${escHtml((n.image||'').slice(0,30))}</td>
      <td>${n.running?'<span class="badge badge-green">running</span>':'<span class="badge badge-red">stopped</span>'}</td>
      <td style="color:var(--muted);font-size:11px">${escHtml(n.uptime||'')}</td>
      <td>${n.is_self?'':'<button class="btn-icon" title="Убить" onclick="doKill(\''+escHtml(n.name)+'\')">🗑</button>'}</td>
    </tr>`).join('')}
  </table></div>`;
}

async function doSpawn(){
  const name = document.getElementById('sp-name').value.trim();
  const port = parseInt(document.getElementById('sp-port').value)||0;
  const bootstrap = document.getElementById('sp-boot').value.trim();
  const el = document.getElementById('sp-result');
  el.innerHTML = '<span style="color:var(--muted)"><span class="spinner" style="width:14px;height:14px;border-width:2px;margin:0;display:inline-block;vertical-align:middle"></span> Создаю контейнер…</span>';
  const r = await apiPost('/api/v1/swarm/spawn', {name, port, bootstrap});
  if(r?.ok){
    el.innerHTML = `<div style="background:#052e16;border:1px solid #14532d;border-radius:8px;padding:10px;color:var(--green)">
      ✅ Узел запущен:<br>
      • Имя: <b>${escHtml(r.name)}</b><br>
      • Порт: <b>${r.port}</b> · Bootstrap: <span class="mono">${escHtml(r.bootstrap)}</span><br>
      • Container: <span class="mono">${escHtml(r.container_id||'?')}</span>
    </div>`;
    toast('Узел породился: '+r.name);
    document.getElementById('sp-name').value=''; document.getElementById('sp-port').value='';
    setTimeout(loadSwarmNodes, 1500);
  }else{
    let hint = '';
    const msg = (r?.error||'fail').toString();
    if(msg.includes('already exists')) hint = '<br>💡 Уже есть контейнер с таким именем — задай другое имя или порт.';
    else if(msg.includes('no free port')) hint = '<br>💡 Все порты 8300–8400 заняты. Освободи или укажи свой.';
    else if(msg.includes('port is already allocated')||msg.includes('address already in use')) hint = '<br>💡 Порт занят. Попробуй другой.';
    el.innerHTML = `<div style="background:#1c0000;border:1px solid #7f1d1d;border-radius:8px;padding:10px;color:var(--red)">
      ✗ <b>${escHtml(msg)}</b>${hint}
    </div>`;
    toast('Ошибка spawn', false);
  }
}

async function doKill(name){
  if(!confirm('Убить узел '+name+'?')) return;
  const r = await apiPost('/api/v1/swarm/kill', {name});
  if(r?.ok){ toast('Узел убит'); loadSwarmNodes(); }
  else toast(r?.error||'fail', false);
}

/* ═══════════════════════════════════════════════════════════════════════
   REFLECT
   ═══════════════════════════════════════════════════════════════════════ */
async function loadReflect(){
  document.getElementById('reflect-out').innerHTML = '<div class="spinner"></div>';
  const r = await api('/api/v1/agent/reflect');
  if(!r?.ok){ document.getElementById('reflect-out').innerHTML='<div class="empty">'+escHtml(r?.error||'fail')+'</div>'; return; }
  const ins = (r.insights||[]).map(i=>`<div style="padding:8px 12px;background:var(--bg3);border-radius:8px;margin-bottom:6px;font-size:14px">${escHtml(i)}</div>`).join('');
  const stats = r.stats||{};
  const recs  = r.recommendations||[];
  const prColor = {high:'#dc2626', med:'#d97706', low:'#4b5563'};
  const prLabel = {high:'HIGH', med:'MED', low:'LOW'};
  const vecIcon = {'размножаться':'🐙','развиваться':'🛠','учиться':'🧠','меняться':'🔄','жить':'❤️'};
  const recsHtml = recs.length
    ? recs.map(x=>`
        <div style="background:var(--bg3);border-left:4px solid ${prColor[x.priority]||'#666'};border-radius:8px;padding:12px;margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <span style="font-weight:600;font-size:14px">${vecIcon[x.vector]||'•'} ${escHtml(x.title)}</span>
            <span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;background:${prColor[x.priority]||'#666'};color:#fff">${prLabel[x.priority]||'?'}</span>
          </div>
          <div style="font-size:12.5px;color:var(--fg2);margin-bottom:6px">${escHtml(x.why)}</div>
          <div style="font-size:12.5px"><span style="color:var(--green)">▸ Действие:</span> ${escHtml(x.action)}</div>
          <div style="font-size:10px;color:var(--fg3);margin-top:6px;text-transform:uppercase;letter-spacing:.5px">vector: ${escHtml(x.vector)}</div>
        </div>`).join('')
    : '<div class="empty">— рекомендаций нет —</div>';

  document.getElementById('reflect-out').innerHTML = `
    ${ins}
    <div style="margin-top:18px">
      <div class="card-title" style="margin-bottom:10px">🧭 Рекомендации (${recs.length})</div>
      ${recsHtml}
    </div>
    <div style="margin-top:14px">
      <div class="card-title" style="margin-bottom:8px">Подробная статистика</div>
      <pre style="background:var(--bg3);padding:12px;border-radius:8px;font-size:11.5px;overflow:auto">${escHtml(JSON.stringify(stats, null, 2))}</pre>
    </div>`;
}

/* ═══════════════════════════════════════════════════════════════════════
   FILES — migrate payload (для старых файлов)
   ═══════════════════════════════════════════════════════════════════════ */
async function migratePayload(){
  if(!confirm('Восстановить payload.bin для всех файлов где его нет?')) return;
  const r = await apiPost('/api/v1/files/migrate_payload', {});
  if(r?.ok){
    toast('Мигрировано: '+r.migrated+' · пропущено: '+r.skipped);
    loadFiles(); loadFilesStats();
  } else toast(r?.error||'fail', false);
}

/* ═══════════════════════════════════════════════════════════════════════
   KNOWLEDGE GRAPH
   ═══════════════════════════════════════════════════════════════════════ */
let knowGraph = { nodes: [], links: [] };

async function loadKnowledgeGraph() {
    const el = document.getElementById('know-canvas');
    if(!el) return;
    const r = await api('/admin/api/memory/knowledge-graph');
    if(!r?.ok) { toast(r?.error||'fail', false); return; }
    
    knowGraph = r;
    document.getElementById('know-stats').innerText = r.nodes.length + ' узлов · ' + r.links.length + ' связей';
    drawKnowledgeGraph();
}

function drawKnowledgeGraph() {
    const canvas = document.getElementById('know-canvas');
    if(!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    canvas.width = w; canvas.height = h;

    ctx.clearRect(0,0,w,h);
    
    // Improved layout: nodes with more connections move to center
    const nodes = knowGraph.nodes.map(n => {
        const linkCount = knowGraph.links.filter(l => l.source === n.id || l.target === n.id).length;
        const angle = Math.random() * Math.PI * 2;
        const dist = Math.random() * (w/3);
        return Object.assign({}, n, {
            x: w/2 + Math.cos(angle) * dist,
            y: h/2 + Math.sin(angle) * dist,
            weight: linkCount
        });
    });

    // Simple physics iterations
    for(let i=0; i<30; i++) {
        for(let a of nodes) {
            for(let b of nodes) {
                if(a===b) continue;
                const dx = a.x - b.x;
                const dy = a.y - b.y;
                const dist = Math.sqrt(dx*dx + dy*dy) || 1;
                if(dist < 80) {
                    const f = (80 - dist) / dist * 0.5;
                    a.x += dx * f; a.y += dy * f;
                    b.x -= dx * f; b.y -= dy * f;
                }
            }
        }
        knowGraph.links.forEach(l => {
            const s = nodes.find(n => n.id === l.source);
            const t = nodes.find(n => n.id === l.target);
            if(s && t) {
                const dx = s.x - t.x; const dy = s.y - t.y;
                const dist = Math.sqrt(dx*dx + dy*dy) || 1;
                const f = dist * 0.01;
                s.x -= dx * f; s.y -= dy * f;
                t.x += dx * f; t.y += dy * f;
            }
        });
    }

    ctx.strokeStyle = 'rgba(51, 65, 85, 0.5)';
    ctx.lineWidth = 1;
    knowGraph.links.forEach(l => {
        const s = nodes.find(n => n.id === l.source);
        const t = nodes.find(n => n.id === l.target);
        if(s && t) {
            ctx.beginPath();
            ctx.moveTo(s.x, s.y);
            ctx.lineTo(t.x, t.y);
            ctx.stroke();
        }
    });

    nodes.forEach(n => {
        ctx.fillStyle = n.id.indexOf('Exp-') === 0 ? '#f472b6' : '#7dd3fc';
        ctx.beginPath();
        ctx.arc(n.x, n.y, 5 + Math.min(n.weight, 10), 0, Math.PI*2);
        ctx.fill();
        
        if(n.weight > 2 || n.id.indexOf('Exp-') !== 0) {
            ctx.fillStyle = '#f8fafc';
            ctx.font = (8 + Math.min(n.weight, 4)) + 'px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(n.label, n.x, n.y + 15 + Math.min(n.weight, 10));
        }
    });
}



/* ═══════════════════════════════════════════════════════════════════════
   Init
   ═══════════════════════════════════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', ()=>{
  initSSE();
  initDragDrop();
  initGraphMouse();
  startTopoAnim();
  loadDashboard();
  setInterval(loadDashboard, 20000);
  // hash routing
  const h = location.hash.slice(1);
  if(h) nav(h);
});

window.addEventListener('resize', ()=>{
  const p = document.querySelector('.page.active');
  if(p?.id==='page-network') drawTopo();
});
</script>
</body>
</html>"""
