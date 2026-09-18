import importlib.util
import json
import re
import unittest
from pathlib import Path

SERVER = Path('/mnt/agents/-Octopus/skills/mcp/skills_mcp_server.py')
SPEC = importlib.util.spec_from_file_location('skills_mcp_server', SERVER)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

class ReadOnlyOpsMCPTests(unittest.TestCase):
    def test_catalog_is_explicitly_read_only(self):
        tools = mod.tool_catalog()
        self.assertGreaterEqual(len(tools), 6)
        for tool in tools:
            self.assertTrue(tool['annotations']['readOnlyHint'])
            self.assertFalse(tool['annotations']['destructiveHint'])
            self.assertFalse(tool['annotations']['openWorldHint'])

    def test_secret_path_is_rejected(self):
        response = json.loads(mod.process_request(json.dumps({
            'id': 1, 'method': 'storage/proof',
            'params': {'target': 'local_path:/mnt/agents/-Octopus/secrets/cas_api_token.txt'},
        })))
        self.assertIn('error', response)
        self.assertIn('target_not_allowlisted', response['error']['message'])

    def test_status_has_trace_and_no_octopus_failures(self):
        response = json.loads(mod.process_request(json.dumps({'id': 2, 'method': 'ops/status', 'params': {}})))
        self.assertRegex(response['trace_id'], r'^octo-.*-ops-status-[0-9a-f]{8}$')
        self.assertEqual(response['result']['octopus_failed_count'], 0)

    def test_graphrag_has_exact_citation(self):
        response = json.loads(mod.process_request(json.dumps({
            'id': 3, 'method': 'graphrag/search', 'params': {'query': 'Octopus', 'limit': 1},
        })))
        self.assertEqual(response['result']['citation_contract'], 'exact_source_path+indexed_sha256')
        citation = response['result']['results'][0]['citation']
        self.assertTrue(citation['source_path'])
        self.assertRegex(citation['source_sha256'], r'^[0-9a-f]{64}$')

if __name__ == '__main__':
    unittest.main()
