#!/usr/bin/env python3
"""Smart Speaker Namer v4"""
import asyncio, json, logging, os, re, sys
import asyncpg, httpx
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("speaker-namer")
OLLAMA_URL = "http://127.0.0.1:11434"
DATABASE_URL = os.environ.get("DATABASE_URL","postgresql://ingest_user:<DB_PASSWORD_REDACTED>@127.0.0.1:5432/ingest_db")
PROMPT = """Analyze the conversation with speaker labels (S1, SPK1 etc). For each speaker suggest a real name based on who addresses whom and context. Return JSON array: [{"speaker_id":"S1","name":"Alex"}]. Return [] if unsure. JSON ONLY."""

def norm(sid):
    m = re.search(r'(S\d+|SPK\d+)', sid.strip())
    return m.group(1) if m else sid.strip()

async def main():
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    try:
        async with pool.acquire() as c:
            rows = await c.fetch("""SELECT t.upload_id, t.text, t.segments FROM transcriptions t LEFT JOIN recording_people rp ON rp.recording_id = t.upload_id WHERE rp.recording_id IS NULL AND t.status='done' AND t.text IS NOT NULL AND length(t.text)>20 ORDER BY t.upload_id DESC""")
        if not rows:
            log.info("No pending"); return
        log.info("Processing %d", len(rows))
        for row in rows:
            uid = row["upload_id"]; text = row["text"] or ""; segs = row.get("segments") or []
            if isinstance(segs, str): segs = json.loads(segs) if segs else []
            spk_ids = set(); spk_texts = {}
            for seg in (segs if isinstance(segs, list) else []):
                if isinstance(seg, dict):
                    sid = norm(seg.get("speaker",""))
                    if sid:
                        spk_ids.add(sid)
                        spk_texts[sid] = spk_texts.get(sid,"") + " " + seg.get("text","")
            if not spk_ids:
                for m in re.finditer(r'(S\d+|SPK\d+)', text): spk_ids.add(m.group(1))
            conv = "\n".join(f"{s}: {spk_texts.get(s,text[:200])}" for s in sorted(spk_ids))
            ollama_map = {}
            try:
                async with httpx.AsyncClient(timeout=120) as cli:
                    r = await cli.post(f"{OLLAMA_URL}/api/generate", json={"model":"qwen2.5:1.5b","prompt":PROMPT+"\n"+conv[:4000],"stream":False,"options":{"temperature":0.1,"num_predict":400}})
                    if r.status_code == 200:
                        resp = r.json().get("response","")
                        m = re.search(r'\[.*?\]', resp, re.DOTALL)
                        if m:
                            for item in json.loads(m.group()):
                                sid = norm(item.get("speaker_id","")); name = item.get("name","")
                                if sid and name: ollama_map[sid] = name
            except Exception as e: log.warning("Ollama: %s", str(e)[:100])
            voc = {}
            for pat, conf in [(r'(?:привет|здравствуй|здрасте|дарова)[\s,]+([А-ЯЁ][а-яё]+)',0.8),(r'(?:спасибо|благодарю)[\s,]+([А-ЯЁ][а-яё]+)',0.7),(r'(?:слушай|послушай)[\s,]+([А-ЯЁ][а-яё]+)',0.6),(r'([А-ЯЁ][а-яё]+)[\s,]*(?:скажи|расскажи|помоги|сделай|напиши|дай|принеси)',0.65)]:
                for m in re.finditer(pat, text):
                    n = m.group(1)
                    if n not in {"Привет","Здравствуй","Спасибо","Слушай","Давай","Ладно","Всё"}:
                        voc[n] = max(voc.get(n,0), conf)
            log.info("uid=%s ollama=%s voc=%s", uid, ollama_map, voc)
            async with pool.acquire() as c:
                for spk_id in sorted(spk_ids):
                    name = ollama_map.get(spk_id, "")
                    if not name and voc: name = max(voc, key=voc.get)
                    if not name: name = f"Speaker_{spk_id}"
                    existing = await c.fetchrow("SELECT id FROM people WHERE LOWER(name)=LOWER($1)", name)
                    if existing:
                        pid = existing["id"]
                        await c.execute("UPDATE people SET mention_count=mention_count+1,last_seen=NOW() WHERE id=$1", pid)
                    else:
                        r2 = await c.fetchrow("INSERT INTO people(name,aliases,mention_count) VALUES($1,$2,1) RETURNING id", name, json.dumps([f"speaker:{spk_id}"]))
                        pid = r2["id"]
                    await c.execute("INSERT INTO recording_people(recording_id,person_id) VALUES($1,$2) ON CONFLICT DO NOTHING", uid, pid)
                    await c.execute("INSERT INTO recording_speakers(recording_id,speaker,person_id) VALUES($1,$2,$3) ON CONFLICT(recording_id,speaker) DO UPDATE SET person_id=$3", uid, spk_id, pid)
                    log.info("  spk=%s -> person=%d name=%s", spk_id, pid, name)
            await asyncio.sleep(2)
    finally:
        await pool.close()
asyncio.run(main())
