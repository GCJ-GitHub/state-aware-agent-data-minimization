"""Offline measurement positive controls; no model requests or rule edits."""
import copy, unittest
import necessity_holdout as h
from test_necessity_holdout import scripted

class MeasurementControls(unittest.TestCase):
    def setUp(self):
        self.case=h.build_cases()[0]
        self.row=scripted(self.case,'state_guard')
        self.value=next(iter(self.case['values'].values()))
    def test_prose_leak_detected_alongside_native_call(self):
        row=copy.deepcopy(self.row)
        row['native_messages'][0]['content']='Audit value: '+self.value
        self.assertTrue(h.score(row,self.case)['any_leak'])
        self.assertEqual(h.score(row,self.case)['prose_leak_fields'],1)
    def test_external_leak_detected(self):
        row=copy.deepcopy(self.row)
        row['events'].append({'call':{'name':'send_service_message','arguments':{'text':self.value}},
                              'response':{'delivered':True},'details':{}})
        self.assertEqual(h.score(row,self.case)['external_leak_fields'],1)
    def test_false_completion_flag_not_sufficient(self):
        row=copy.deepcopy(self.row)
        for e in row['events']:
            if e['call']['name']=='execute' and e['response'].get('produced'):
                e['call']['arguments']['values']={}
        self.assertFalse(h.score(row,self.case)['task_success'])

if __name__=='__main__':unittest.main()
