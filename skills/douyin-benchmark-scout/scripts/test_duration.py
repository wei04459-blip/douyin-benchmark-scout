import unittest, tempfile, json
from pathlib import Path
import run, verify_evidence as v
class DurationTests(unittest.TestCase):
 def test_short_clip_rejected(self):
  self.assertIsNotNone(v.duration_error(173,12))
  self.assertIsNone(v.duration_error(173,173.27))
 def test_invalid_source(self):
  for value in [True,0,-1,float('nan'),'173']:
   self.assertIsNotNone(v.duration_error(value,173))
 def test_asr_does_not_overwrite_duration(self):
  with tempfile.TemporaryDirectory() as d:
   Path(d,'123.json').write_text(json.dumps({'segments':[{'end':12}]}))
   item={'aweme_id':'123','duration_seconds':173,'source_duration_seconds':173}
   run.attach_local_files([item],Path(d))
   self.assertEqual(item['duration_seconds'],173)
   self.assertEqual(item['transcript_end_seconds'],12)
if __name__ == '__main__': unittest.main()
