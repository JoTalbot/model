import os
import unittest
from memory_api import init_db, save_memory_item, search_memory

TEST_DB = "/tmp/test_pwa_memory.db"

class TestPWAMemory(unittest.TestCase):
    def setUp(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        init_db(TEST_DB)

    def tearDown(self):
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)

    def test_save_and_search(self):
        item = save_memory_item("id1", "note", "Тест PWA", "Контент универсальной памяти", ["тест"], db_path=TEST_DB)
        self.assertEqual(item["id"], "id1")

        res = search_memory("универсальной", db_path=TEST_DB)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["title"], "Тест PWA")

if __name__ == "__main__":
    unittest.main()
