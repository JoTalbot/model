"""AIOS Multi-Modal Vision & Document OCR Pipeline.
Processes images, diagrams, documents, and screenshots using Groq LPU Vision (qwen/qwen3.8-27b)
and Google Gemini 2.5 Flash, extracting structured text, OCR, and facts directly into the Knowledge Fabric.
"""
import os, sys, time, json, base64, httpx
from typing import Dict, Any, Optional

sys.path.insert(0, '/opt')
sys.path.insert(0, '/opt/aios')

try:
    from aios.llm.llm_balancer import LLMBalancer
    balancer = LLMBalancer.get_instance()
except Exception:
    balancer = None

try:
    from aios.memory_fabric.knowledge_graph import KnowledgeFabric
    knowledge_fabric = KnowledgeFabric.get_instance()
except Exception:
    knowledge_fabric = None

class VisionPipeline:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._load_keys()

    def _load_keys(self):
        secrets_file = "/etc/octopus/secrets.env"
        self.groq_keys = []
        self.gemini_keys = []
        if os.path.exists(secrets_file):
            with open(secrets_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        v = v.strip('"').strip("'")
                        if k.startswith("GROQ_API_KEY"):
                            for sub_k in v.split(","):
                                if sub_k.strip() and sub_k.strip() not in self.groq_keys:
                                    self.groq_keys.append(sub_k.strip())
                        elif k.startswith("GEMINI_API_KEY"):
                            for sub_k in v.split(","):
                                if sub_k.strip() and sub_k.strip() not in self.gemini_keys:
                                    self.gemini_keys.append(sub_k.strip())

    async def analyze_image_bytes(self, image_bytes: bytes, prompt: str = "Опиши подробно, что изображено на картинке, извлеки весь текст (OCR) и ключевые факты.", mime_type: str = "image/jpeg") -> Dict[str, Any]:
        t0 = time.time()
        b64_img = base64.b64encode(image_bytes).decode('utf-8')
        
        # 1. Try Gemini 2.5 Flash Vision
        if self.gemini_keys:
            for g_key in self.gemini_keys:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={g_key}"
                    payload = {
                        "contents": [{
                            "parts": [
                                {"text": prompt},
                                {"inline_data": {"mime_type": mime_type, "data": b64_img}}
                            ]
                        }]
                    }
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(url, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                            dt = round((time.time() - t0)*1000, 1)
                            
                            # Ingest into Knowledge Fabric
                            if knowledge_fabric:
                                try:
                                    knowledge_fabric.record_episode(
                                        title=f"Vision Analysis ({time.strftime('%H:%M:%S')})",
                                        content=f"Запрос: {prompt}\nРезультат OCR/Vision: {text[:1000]}",
                                        metadata={"type": "vision_ocr", "model": "gemini-2.5-flash", "latency_ms": dt}
                                    )
                                except Exception:
                                    pass
                                    
                            return {"ok": True, "provider": "gemini-2.5-flash", "latency_ms": dt, "analysis": text}
                except Exception:
                    continue

        # 2. Try Groq Multimodal Vision (qwen/qwen3.8-27b)
        if self.groq_keys:
            for q_key in self.groq_keys:
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {q_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "qwen/qwen3.8-27b",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64_img}"}}
                                ]
                            }
                        ],
                        "max_tokens": 1000
                    }
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        resp = await client.post(url, headers=headers, json=payload)
                        if resp.status_code == 200:
                            data = resp.json()
                            text = data["choices"][0]["message"]["content"].strip()
                            dt = round((time.time() - t0)*1000, 1)
                            return {"ok": True, "provider": "groq-qwen3.8-27b", "latency_ms": dt, "analysis": text}
                except Exception:
                    continue

        return {"ok": False, "error": "All multimodal vision providers failed"}

    def analyze_image_sync(self, image_bytes: bytes, prompt: str = "Опиши подробно, что изображено на картинке.", mime_type: str = "image/jpeg") -> Dict[str, Any]:
        import asyncio
        try:
            return asyncio.run(self.analyze_image_bytes(image_bytes, prompt, mime_type))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.analyze_image_bytes(image_bytes, prompt, mime_type))
            finally:
                loop.close()

vision_pipeline = VisionPipeline.get_instance()

if __name__ == "__main__":
    # Test with a 1x1 PNG dummy image
    test_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    res = vision_pipeline.analyze_image_sync(test_png, prompt="Что на изображении?", mime_type="image/png")
    print("Vision Pipeline Test Result:")
    print(json.dumps(res, indent=2, ensure_ascii=False))
