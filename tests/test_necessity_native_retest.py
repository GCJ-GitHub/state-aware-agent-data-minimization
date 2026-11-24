"""Offline native-wire checks. Scripted controls are never model results."""
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import necessity_native_retest as n


def scripted(case,arm):
    cache,approved={},set()
    pending=None
    last=None
    def emit(name,args,index):
        nonlocal last
        last={'name':name,'arguments':args}
        return {'role':'assistant','content':'','tool_calls':[{'id':f'offline-{index}',
                    'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}, {
                    'role':'conversation','reasoning':'','usage':{},'finish_reason':'tool_calls'}
    def use_values(response,index):
        session=response['sessions'][-1]
        a=next(a for a in session['enabled_actions'] if a['action']==pending['action'])
        key=(session['session'],a['action'])
        if a['confirmation_required'] and key not in approved:
            return emit('confirm_action',{'session':key[0],'action':key[1]},index)
        return emit('execute',{'session':key[0],'action':key[1],
                     'values':{f:cache[f] for f in a['input_fields']}},index)
    def infer(messages,index):
        nonlocal pending
        if index==0:
            boot=json.loads(messages[-1]['content'].split('\n',1)[1])
            response=boot['initial_planning']
            previous=None
        else:
            assert messages[-1]['role']=='tool'
            assert messages[-1]['tool_call_id']==f'offline-{index-1}'
            response=json.loads(messages[-1]['content'])
            previous=last['name']
            cache.update(response.get('values',{}))
            if response.get('approved'):
                approved.add((last['arguments']['session'],last['arguments']['action']))
        if response['workflow_complete']:
            return {'role':'assistant','content':'Workflow complete.'},{'role':'conversation','reasoning':'','usage':{},'finish_reason':'stop'}
        if response.get('refresh_public_state'):
            return emit('refresh_state',{},index)
        active=response['sessions'][-1] if response['sessions'] else None
        if active and active['session_stale']:
            if previous=='refresh_state' and response['status']=='ready':
                return emit('propose_plan',{'nodes':response['plans'][0]['nodes']},index)
            return emit('refresh_state',{},index)
        if response['status']=='need_evidence':
            return emit('probe',{'name':response['recommended_probe']},index)
        if previous=='issue_read':
            if response['fields']:
                return emit('read_details',{'grant':response['grant'],'fields':response['fields']},index)
            return use_values(response,index)
        if previous in ('read_details','confirm_action') and not response.get('error'):
            return use_values(response,index)
        if active and active['enabled_actions']:
            pending={'session':active['session'],'action':active['enabled_actions'][0]['action']}
            return emit('issue_read',pending,index)
        return emit('propose_plan',{'nodes':response['plans'][0]['nodes']},index)
    return n.episode(case,arm,19,infer)


class NativeControls(unittest.TestCase):
    def test_native_only_and_no_inferred_parameters(self):
        valid={'content':'','tool_calls':[{'id':'test','function':{'name':'probe','arguments':'{"name":"check_fee"}'}}]}
        self.assertEqual(n.decode_native(valid),({'name':'probe','arguments':{'name':'check_fee'}},None))
        self.assertEqual(n.decode_native({'content':'{"name":"inspect","arguments":{}}'})[1],'no_native_call')
        for message in [
            {'tool_calls':[{'id':'test','function':{'name':'probe','arguments':'{}'}}]},
            {'tool_calls':[{'id':'test','function':{'name':'inspect','arguments':''}}]},
            {'tool_calls':[{'function':{'name':'inspect','arguments':'{}'}}]},
            {'tool_calls':[{'id':'test','function':{'name':'invented','arguments':'{}'}}]},
            {'tool_calls':valid['tool_calls']*2}]:
            self.assertIsNone(n.decode_native(message)[0])

    def test_initial_advice_visible_without_fabricated_tool_call(self):
        case=n.old.build_cases()[0]
        messages={a:n.initial_messages(n.old.Backend(case,a),case) for a in n.ARMS}
        self.assertEqual(messages['fixed_soft'],messages['fixed_enforced'])
        self.assertEqual(messages['planned_soft'],messages['planned_enforced'])
        for a,ms in messages.items():
            self.assertEqual([m['role'] for m in ms],['system','user','user'])
            boot=json.loads(ms[-1]['content'].split('\n',1)[1])
            self.assertEqual(boot['initial_planning']['recommended_probe'],'check_fee' if a.startswith('planned') else 'check_speed')
            for value in n.old.make_verifier(case).authority._values.values():
                self.assertNotIn(str(value),json.dumps(ms))

    def test_48_native_workflows_and_scope_controls(self):
        for case in n.old.build_cases():
            for arm in n.ARMS:
                with self.subTest(case=case['id'],arm=arm):
                    row=scripted(case,arm)
                    result=n.score(row,case)
                    self.assertTrue(result['task_success'])
                    self.assertEqual(result['native_protocol_errors'],0)
                    if arm.endswith('enforced'):
                        self.assertEqual(result['outside_justification_fields'],0)
                    if case['family']=='evidence_drift':
                        self.assertEqual(result['expired_evidence_fields'],0 if arm.endswith('enforced') else 2)
                        self.assertEqual(result['blocked_reads'],1 if arm.endswith('enforced') else 0)

    def test_native_content_is_not_lost_in_prose_privacy_scoring(self):
        case=n.old.build_cases()[2]
        row=scripted(case,'fixed_soft')
        row['native_messages'][0]['content']=n.old.make_verifier(case).authority._values['order.wallet_ref']
        self.assertEqual(n.score(row,case)['prose_leak_fields'],1)

    def test_full_request_has_native_tools_and_common_budget(self):
        body=n.request_body([{'role':'user','content':'synthetic'}],19)
        self.assertEqual(body['max_tokens'],512)
        self.assertFalse(body['parallel_tool_calls'])
        self.assertEqual(body['tool_choice'],'auto')
        self.assertEqual(len(body['tools']),len(n.old.TOOLS))


if __name__=='__main__':unittest.main()
