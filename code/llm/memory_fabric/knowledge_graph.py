"""Octopus AIOS Knowledge Fabric - Long-Term Semantic Memory & Graph Engine.
Integrates PostgreSQL pgvector (HNSW cosine similarity), Entity-Relation Graph (NER),
and Edge RAG synchronization across the 3-node cluster.
"""
import os, sys, time, json, re, hashlib, psycopg2, psycopg2.extras
from typing import Dict, Any, List, Optional
import httpx

DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/app_db")

def get_db():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn

def init_schema():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_entities (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) UNIQUE NOT NULL,
                entity_type VARCHAR(64) NOT NULL,
                description TEXT,
                metadata JSONB DEFAULT '{}'::jsonb,
                embedding vector(768),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            
            CREATE TABLE IF NOT EXISTS knowledge_relations (
                id SERIAL PRIMARY KEY,
                source_id INT REFERENCES knowledge_entities(id) ON DELETE CASCADE,
                target_id INT REFERENCES knowledge_entities(id) ON DELETE CASCADE,
                relation_type VARCHAR(64) NOT NULL,
                weight FLOAT DEFAULT 1.0,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE (source_id, target_id, relation_type)
            );

            CREATE TABLE IF NOT EXISTS knowledge_episodes (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                entities JSONB DEFAULT '[]'::jsonb,
                embedding vector(768),
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_entities_embedding ON knowledge_entities USING hnsw (embedding vector_cosine_ops);
            CREATE INDEX IF NOT EXISTS idx_episodes_embedding ON knowledge_episodes USING hnsw (embedding vector_cosine_ops);
            """)
    print("✅ Knowledge Graph & pgvector schema initialized successfully!")

def get_embedding(text: str) -> List[float]:
    """Generates 768-dim normalized embedding via Ollama or fallback deterministic vector."""
    try:
        r = httpx.post("http://127.0.0.1:11434/api/embeddings", json={"model": "nomic-embed-text", "prompt": text[:2000]}, timeout=3.0)
        if r.status_code == 200:
            emb = r.json().get("embedding", [])
            if len(emb) == 768:
                return emb
    except Exception:
        pass
    
    # Deterministic fallback embedding generator (768 dimensions)
    h = hashlib.sha256(text.encode('utf-8')).hexdigest()
    vec = []
    for i in range(768):
        sub = hashlib.sha256(f"{h}_{i}".encode('utf-8')).hexdigest()[:4]
        val = (int(sub, 16) / 65535.0) * 2.0 - 1.0
        vec.append(val)
    norm = sum(x**2 for x in vec) ** 0.5
    return [round(x / norm, 6) for x in vec]

class KnowledgeFabric:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        init_schema()

    def add_entity(self, name: str, entity_type: str, description: str = "", metadata: Optional[Dict] = None) -> int:
        emb = get_embedding(f"{name}: {description}")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO knowledge_entities (name, entity_type, description, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
                RETURNING id;
                """, (name, entity_type, description, json.dumps(metadata or {}), emb))
                return cur.fetchone()[0]

    def add_relation(self, source_name: str, target_name: str, relation_type: str, weight: float = 1.0) -> bool:
        src_id = self.add_entity(source_name, "general")
        tgt_id = self.add_entity(target_name, "general")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO knowledge_relations (source_id, target_id, relation_type, weight)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_id, target_id, relation_type) DO UPDATE SET weight = EXCLUDED.weight;
                """, (src_id, tgt_id, relation_type, weight))
                return True

    def record_episode(self, title: str, content: str, metadata: Optional[Dict] = None) -> int:
        from aios.llm.llm_balancer import LLMBalancer
        balancer = LLMBalancer.get_instance()
        
        # Extract entities via LLM
        prompt = f"Извлеки из текста ключевые сущности и связи в формате JSON: {{\"entities\": [\"Name1\", \"Name2\"], \"relations\": [{{\"source\": \"A\", \"target\": \"B\", \"relation\": \"type\"}}]}}.\n\nТекст:\n{content[:1500]}"
        raw_res = balancer.generate_sync(prompt, task_type="fast")
        
        extracted_entities = []
        try:
            match = re.search(r'\{.*\}', raw_res, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                extracted_entities = data.get("entities", [])
                for rel in data.get("relations", []):
                    if "source" in rel and "target" in rel and "relation" in rel:
                        self.add_relation(rel["source"], rel["target"], rel["relation"])
        except Exception:
            pass

        emb = get_embedding(f"{title}\n{content}")
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                INSERT INTO knowledge_episodes (title, content, entities, embedding, metadata)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """, (title, content, json.dumps(extracted_entities), emb, json.dumps(metadata or {})))
                ep_id = cur.fetchone()[0]
                
        # Index extracted entities
        for ent in extracted_entities:
            self.add_entity(str(ent), "extracted", f"Упомянуто в эпизоде: {title}")
            
        return ep_id

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        emb = get_embedding(query)
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                SELECT id, title, content, entities, 1 - (embedding <=> %s::vector) AS similarity
                FROM knowledge_episodes
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """, (emb, emb, limit))
                episodes = cur.fetchall()

                cur.execute("""
                SELECT e.name, e.entity_type, e.description, 1 - (e.embedding <=> %s::vector) AS similarity
                FROM knowledge_entities e
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s;
                """, (emb, emb, limit))
                entities = cur.fetchall()

        return {
            "query": query,
            "episodes": [dict(e) for e in episodes],
            "entities": [dict(en) for en in entities]
        }

    def get_graph_stats(self) -> Dict[str, Any]:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM knowledge_entities;")
                num_entities = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM knowledge_relations;")
                num_relations = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM knowledge_episodes;")
                num_episodes = cur.fetchone()[0]
        return {
            "entities_count": num_entities,
            "relations_count": num_relations,
            "episodes_count": num_episodes
        }

knowledge_fabric = KnowledgeFabric.get_instance()

if __name__ == "__main__":
    kf = KnowledgeFabric.get_instance()
    print("Initial stats:", kf.get_graph_stats())
    
    # Ingest a sample episode
    ep_id = kf.record_episode(
        "Groq 13-Key Swarm Harvest",
        "Команда AIOS развернула конвейер сбора ключей Groq на базе Gmail Dot-Trick и 2Captcha RPA. Все 13 ключей были интегрированы в MultiKeyRotatingProvider.",
        {"source": "agent_automation"}
    )
    print(f"Recorded episode ID: {ep_id}")
    
    # Test vector search
    res = kf.search("Как работает сбор ключей Groq?")
    print("Search results:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
