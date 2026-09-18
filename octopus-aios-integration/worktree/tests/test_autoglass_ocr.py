import asyncio
import pytest
import json
from pathlib import Path
from swarm.business.autoglass import GlassCatalog, AutoglassOCRProcessor, GlassItem
from swarm.media.processor import MediaStore
from swarm.memory.repository import MemoryRepository
from swarm.memory.adapters.local_scratch import LocalScratchAdapter
from swarm.memory.composite import CompositeMemoryPort

class MockLLM:
    async def complete(self, messages):
        return json.dumps([
            {
                "name": "Лобовое стекло BMW X5",
                "glass_type": "лобовое",
                "makes": ["BMW"],
                "models": ["X5"],
                "price": 15000.0,
                "currency": "RUB",
                "supplier": "AutoGlass Pro"
            }
        ])

@pytest.fixture
async def repo(tmp_path):
    adapter = LocalScratchAdapter(str(tmp_path))
    port = CompositeMemoryPort({"file": adapter})
    return MemoryRepository(port)

@pytest.mark.asyncio
async def test_autoglass_ocr_processor(repo, tmp_path):
    catalog = GlassCatalog(repo)
    media_store = MediaStore(repo)
    llm = MockLLM()
    processor = AutoglassOCRProcessor(catalog, media_store, llm)
    
    # Create a dummy image file
    img_path = tmp_path / "invoice.jpg"
    img_path.write_bytes(b"dummy image content")
    
    # Mock ocr_image to return text
    import swarm.business.autoglass
    import swarm.media.processor
    
    original_ocr = swarm.media.processor.ocr_image
    swarm.media.processor.ocr_image = lambda path, **kwargs: "Invoice: Windshield BMW X5 - 15000 RUB"
    
    try:
        items = await processor.process_file(img_path)
        
        assert len(items) == 1
        assert items[0].name == "Лобовое стекло BMW X5"
        assert items[0].price == 15000.0
        
        # Verify it's in the catalog
        catalog_items = await catalog.search(make="BMW")
        assert len(catalog_items) == 1
        assert catalog_items[0].name == "Лобовое стекло BMW X5"
        
    finally:
        swarm.media.processor.ocr_image = original_ocr
