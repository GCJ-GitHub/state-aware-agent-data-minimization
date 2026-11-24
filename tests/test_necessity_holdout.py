"""Mechanics fixtures only; not autonomous model evidence."""
import json, unittest
import necessity_holdout as h


def scripted(case, arm):
    state={'info':None,'session':None,'grant':None,'values':{}}
    def infer(messages,index):
        if index==0:name,args='inspect',{}
        else:
            r=json.loads(messages[-1]['content']);state['values'].update(r.get('values',{}));state['info']=r
            if r.get('workflow_complete'):return {'role':'assistant','content':'Completed.'},{'finish_reason':'stop'}
            if r.get('refresh_public_state') or any(s['session_stale'] for s in r.get('sessions',[]) if s['session']==state['session']):
                name,args='refresh_state',{};state['session']=None;state['grant']=None
            elif not state['session']:
                if r.get('session'):state['session']=r['session']
                else:name,args='propose_plan',{'nodes':r['plans'][0]['nodes']};return msg(name,args,index)
                name,args=next_step(r,state)
            else:name,args=next_step(r,state)
        return msg(name,args,index)
    def msg(name,args,index):
        return {'role':'assistant','content':None,'tool_calls':[{'id':f'test{index}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},{'finish_reason':'tool_calls'}
    def next_step(r,state):
        sid=state['session'];session=next(s for s in r['sessions'] if s['session']==sid)
        action=session['enabled_actions'][0];aid=action['action']
        if r.get('grant'):state['grant']=r['grant']
        missing=[f for f in action['input_fields'] if f not in state['values']]
        if missing and state['grant'] is None:return 'issue_read',{'session':sid,'action':aid}
        if missing:
            grant=state['grant'];state['grant']=None
            return 'read_details',{'grant':grant,'fields':missing}
        if action['confirmation_required'] and not r.get('approved'):return 'confirm_action',{'session':sid,'action':aid}
        return 'execute',{'session':sid,'action':aid,'values':{f:state['values'][f] for f in action['input_fields']}}
    return h.episode(case,arm,19,infer)


class HoldoutTests(unittest.TestCase):
    def test_pairs(self):
        cases=h.build_cases();self.assertEqual(len(cases),120)
        for a,b in zip(cases[::2],cases[1::2]):
            for key in ('user','specs','values','order'):self.assertEqual(a[key],b[key])
            self.assertNotEqual(a['facts'],b['facts'])
    def test_oracle_agrees_with_initial_contracts(self):
        for c in h.build_cases():
            b=h.Backend(c,'state_guard')
            self.assertIn(h.oracle(c,c['facts']),[set(p['nodes']) for p in b.info()['plans']])
    def test_all_scripted_paths_and_scores(self):
        for c in h.build_cases():
            for arm in h.ARMS:
                row=scripted(c,arm);score=h.score(row,c)
                self.assertTrue(score['task_success'],(c['id'],arm,row['events'][-1]))
                if arm=='state_guard':self.assertEqual(score['outside_justification_fields'],0)
    def test_block_stale_grant(self):
        c=next(c for c in h.build_cases() if c['family']=='switch')
        for arm in ('agent_only','state_guard'):
            b=h.Backend(c,arm);p=b.info()['plans'][0]['nodes'];r,_=b.call('propose_plan',{'nodes':p});sid=r['session'];aid=b.session_info(sid)['enabled_actions'][0]['action']
            r,_=b.call('issue_read',{'session':sid,'action':aid})
            response,details=b.call('read_details',{'grant':r['grant'],'fields':r['fields']})
            self.assertEqual(details.get('read_blocked'),arm=='state_guard')
    def test_native_loop_unchanged(self):
        self.assertIs(h.episode.__code__,h.native.episode.__code__)

if __name__=='__main__':unittest.main()
