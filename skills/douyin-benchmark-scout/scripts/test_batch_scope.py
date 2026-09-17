import copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import research_batch as r

class ScopeTests(unittest.TestCase):
 def setUp(self):
  self.b={'items':[{'aweme_id':str(10000000000+j),'keyword':k,'identity_evidence':'page','source_duration_seconds':10,'source_duration_evidence':'player'} for j,k in enumerate(['a','a','b','b','c','c'])],'keywords':['a','b','c'],'target_count':6,'target_per_keyword':2}
 def test_exact_scope_passes(self): self.assertEqual(r.scope_errors(self.b),[])
 def test_short_batch_fails(self):
  self.b['items'].pop(); self.assertTrue(r.scope_errors(self.b))
 def test_total_does_not_replace_each_keyword(self):
  self.b['items'][0]['keyword']='b';self.assertTrue(r.scope_errors(self.b))
 def test_duplicates_do_not_fill_quota(self):
  self.b['items'][1]['aweme_id']=self.b['items'][0]['aweme_id'];self.assertTrue(r.scope_errors(self.b))
 def test_seen_items_are_not_new(self):
  self.b['excluded_aweme_ids']=[self.b['items'][0]['aweme_id']];self.assertTrue(r.scope_errors(self.b))
 def test_legacy_without_quota_unchanged(self):
  self.b.pop('target_count');self.b.pop('target_per_keyword');self.b['items']=self.b['items'][:2];self.assertEqual(r.scope_errors(self.b),[])
 def test_scope_failure_overrides_material_success(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/'batch';r.initialize(root,self.b['keywords'],'scope');b=r.read(root/'batch.json');b.update(self.b);b['items'].pop();r.save(root/'batch.json',b)
   with patch.object(r,'audit',return_value={'ready':True,'errors':[]}),patch.object(r,'search_summary',return_value=[{'status':'results_observed','scope_complete':True}]):
    result=r.evaluate(root)
   self.assertFalse(result['ready']);self.assertFalse(result['scope_complete'])

if __name__=='__main__':unittest.main()
