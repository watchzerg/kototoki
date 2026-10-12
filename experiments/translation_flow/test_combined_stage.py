"""Combined geometry, output reservation and exact ordered protocol interactions."""
import json
from pathlib import Path
import tempfile
import unittest
from .test_v2_common_source import source_fixture
from .test_v2_ordered_text import FakeClient, settings, valid_text, accepts_generated_grammar
from .test_worker import budget
from .v2_prepare import prepare
from .v2_worker import load_plan, run_window
from .v2_id_text import ordered_grammar

class CombinedStageTests(unittest.TestCase):
 def test_source_blocks_budget_and_ordered_native_request_preserve_all_targets(self):
  with tempfile.TemporaryDirectory() as temp:
   args=source_fixture(Path(temp))
   prepare(**args,recipe='id-text-ordered',target_size=5,common_context_block_size=60,n_predict=3072)
   plan,workloads=load_plan(args['output']/'session-plan.json')
   item,_,windows=workloads[0]
   self.assertEqual(item['n_predict'],3072)
   self.assertEqual([uid for w in windows for uid in w['translate_ids']],[str(i) for i in range(135)])
   self.assertEqual(len(windows),27)
   provenance=json.loads((args['output']/'preparation.json').read_text())
   self.assertEqual(provenance['source_visibility_policy']['block_size'],60)
   self.assertEqual(provenance['generation_budget']['n_predict'],3072)
   for window in (windows[0],windows[11],windows[12],windows[-1]):
    content=valid_text(window['translate_ids'])
    client=FakeClient([content],tokens=7)
    row=run_window(client,window,item,8192,budget(max_estimated_tokens=100000),{'verified':False,'first_response_checked':False})
    self.assertEqual(row['status'],'delivered',row)
    self.assertEqual(set(row['translations']),set(window['translate_ids']))
    request=client.requests[0]
    self.assertEqual(request['n_predict'],3072)
    self.assertEqual(request['grammar'],ordered_grammar(window['translate_ids']))
    self.assertTrue(accepts_generated_grammar(request['grammar'],content))
    self.assertEqual(row['auxiliary_seconds'],0)
 def test_common_source_never_makes_readonly_id_deliverable(self):
  with tempfile.TemporaryDirectory() as temp:
   args=source_fixture(Path(temp));prepare(**args,recipe='id-text-ordered',target_size=5,common_context_block_size=60)
   _,workloads=load_plan(args['output']/'session-plan.json');item,_,windows=workloads[0];window=windows[0]
   extra=next(c['id'] for c in window['context'] if c['id'] not in window['translate_ids'])
   content=valid_text(window['translate_ids'])+'\n[['+extra+']]synthetic'
   client=FakeClient([content,content]);row=run_window(client,window,item,8192,budget(max_estimated_tokens=100000),{'verified':False,'first_response_checked':False})
   self.assertEqual(row['status'],'translation_failed');self.assertEqual(row['translations'],{})
   self.assertEqual(len(client.requests),2);self.assertEqual(client.requests[0],client.requests[1])
   self.assertFalse(accepts_generated_grammar(client.requests[0]['grammar'],content))
if __name__=='__main__':unittest.main()
