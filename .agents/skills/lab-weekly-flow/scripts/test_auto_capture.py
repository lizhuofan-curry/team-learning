from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import auto_capture as a


class AutoCaptureTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)
        self.config={'enabled':True,'workflow_root':str(self.root),'platforms':['weixin']}
        self.when=1793156400

    def payload(self,user,assistant='这是AI解释，尚未独立核验。',turn='t1',platform='weixin'):
        return {'hook_event_name':'post_llm_call','session_id':'synthetic-session','extra':{'platform':platform,'turn_id':turn,'user_message':user,'assistant_response':assistant,'conversation_history':[{'role':'system','content':'must-never-be-saved'},{'role':'user','content':'unrelated-secret-history'}]}}

    def test_learning_turn_saved_as_original_and_ai_reply_separately(self):
        raw='今天学习了模型检索，计划明天完成练习，目前还没完成。'
        result=a.handle(self.payload(raw),self.config,self.when)
        self.assertEqual(result['status'],'captured')
        events=a.flow.export(self.root)['events']
        self.assertEqual(len(events),2)
        original=next(x for x in events if x['kind']=='user-original')
        self.assertEqual(original['text'],raw)
        self.assertEqual(original['category'],'plan')
        all_text=''.join(x['text'] for x in events)
        self.assertNotIn('must-never-be-saved',all_text)
        self.assertNotIn('unrelated-secret-history',all_text)

    def test_same_turn_retried_does_not_add_events(self):
        p=self.payload('解释一下Agent的工具调用')
        x=a.handle(p,self.config,self.when)
        self.assertEqual(a.handle(p,self.config,self.when+1),x)
        self.assertEqual(len(a.flow.export(self.root)['events']),2)

    def test_manual_original_already_saved_is_reused(self):
        text='今天复习数据结构'
        date='2026-10-28'
        old=a.flow.capture(self.root,date,text,'wechat','user-original','real-manual-id')
        result=a.handle(self.payload(text),self.config,self.when)
        self.assertEqual(result['event_ids'][0],a.flow.read_json(old)['id'])
        self.assertEqual(len(a.flow.export(self.root)['events']),2)

    def test_article_discussion_without_record_keyword_is_captured(self):
        result=a.handle(self.payload('https://claude.dev/blog/solving-code-review-at-anthropic/'),self.config,self.when)
        self.assertEqual(result['status'],'captured')
        self.assertEqual(a.flow.export(self.root)['events'][0]['category'],'resource')

    def test_real_workflow_question_does_not_require_record_keyword(self):
        result=a.handle(self.payload('解释一下目前工作流'),self.config,self.when)
        self.assertEqual(result['status'],'captured')

    def test_unrelated_optout_and_credentials_are_not_saved(self):
        for n,text in enumerate(['今天中午吃什么','不要记录：这是一段学习私事','你好','学习API_KEY="'+('x'*30)+'"']):
            with self.subTest(text=text):
                self.assertEqual(a.handle(self.payload(text,turn=str(n)),self.config,self.when)['status'],'skipped')
        self.assertEqual(a.flow.export(self.root)['events'],[])

    def test_recent_followup_is_captured_but_not_after_unrelated_turn(self):
        a.handle(self.payload('学习模型检索'),self.config,self.when)
        result=a.handle(self.payload('没看懂，举个例子',turn='t2'),self.config,self.when+10)
        self.assertEqual(result['status'],'captured')
        a.handle(self.payload('今天中午吃什么',turn='t3'),self.config,self.when+20)
        self.assertEqual(a.handle(self.payload('为什么',turn='t4'),self.config,self.when+30)['status'],'skipped')

    def test_optout_or_credential_turn_ends_followup_window(self):
        for reason in ['私人内容：不想记录这件事', '学习API_KEY='+('x'*30)]:
            a.handle(self.payload('今天学习数据结构',turn=reason+'1'),self.config,self.when)
            a.handle(self.payload(reason,turn=reason+'2'),self.config,self.when+10)
            result=a.handle(self.payload('继续解释一下',turn=reason+'3'),self.config,self.when+20)
            self.assertEqual(result['status'],'skipped')

    def test_voice_and_quoted_gateway_input_are_not_originals(self):
        for n, raw in enumerate(['"今天学习模型，计划明天完成实验"', '[Voice transcription provided by Weixin]\n今天学习模型', '"今天学习模型"\n\n补充：计划明天完成实验']):
            result=a.handle(self.payload(raw,turn='voice'+str(n)),self.config,self.when)
            self.assertEqual(result['input_kind'],'assistant-summary')
            event=a.flow.read_json(self.root/'收件箱'/'2026-10-28'/(result['event_ids'][0]+'.json'))
            self.assertIn(raw,event['text'])
            self.assertIn('待本人核对',event['text'])
        self.assertFalse(any(e['kind']=='user-original' for e in a.flow.export(self.root)['events']))

    def test_followup_window_expires(self):
        a.handle(self.payload('学习模型检索'),self.config,self.when)
        self.assertEqual(a.handle(self.payload('为什么',turn='t2'),self.config,self.when+1900)['status'],'skipped')

    def test_wrong_platform_or_missing_fields_does_not_capture(self):
        self.assertEqual(a.handle(self.payload('学习模型',platform='cli'),self.config,self.when)['status'],'ignored_platform')
        self.assertEqual(a.handle({'hook_event_name':'post_llm_call','extra':{'platform':'weixin'}},self.config,self.when)['status'],'missing_current_turn_fields')
        self.assertFalse((self.root/'收件箱').exists())


if __name__=='__main__':unittest.main()
