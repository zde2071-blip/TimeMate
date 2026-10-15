import unittest
from unittest.mock import patch

from backend.core import ai_services
class AIServiceTests(unittest.TestCase):
    def test_model_catalog_keeps_ids_and_provider_display_fields(self):
        data={'data':[{'id':'deepseek-flash','name':'DeepSeek-V4.1-Flash'},
                      {'id':'claude-id','display_name':'Claude Example'},
                      {'id':'gemini-id','displayName':'Gemini Example'},
                      {'id':'plain-id'}, {'id':'bad-name','name':{'invalid':True}}]}
        with patch.object(ai_services,'request_json',return_value=data):
            models=ai_services.list_models(self.config())
        self.assertIn('deepseek-flash',models)
        self.assertNotIn('DeepSeek-V4.1-Flash',models)
        self.assertEqual(models.names,{'deepseek-flash':'DeepSeek-V4.1-Flash','claude-id':'Claude Example','gemini-id':'Gemini Example'})

    def test_claude_pagination_keeps_names(self):
        pages=[{'data':[{'id':'a','display_name':'Claude A'}],'has_more':True,'last_id':'a'},
               {'data':[{'id':'b','display_name':'Claude B'}],'has_more':False}]
        with patch.object(ai_services,'request_json',side_effect=pages):
            models=ai_services.list_models(self.config('claude'))
        self.assertEqual(models,['a','b'])
        self.assertEqual(models.names,{'a':'Claude A','b':'Claude B'})

    def config(self, provider='deepseek'):
        return {'provider':provider,'base':ai_services.PROVIDERS[provider]['base'],
                'model':'deepseek-flash' if provider=='deepseek' else 'test-model','key':'test-key'}

    def response(self, content, reason='stop', reasoning=None):
        return {'choices':[{'message':{'content':content,'reasoning_content':reasoning},'finish_reason':reason}]}

    def test_deepseek_disables_thinking_and_keeps_output_budget(self):
        with patch.object(ai_services,'request_json',return_value=self.response('{"summary":"完成"}')) as request:
            result=ai_services.complete(self.config(),'输出 JSON',{'body':'通知'})
        self.assertEqual(result,{'summary':'完成'})
        payload=request.call_args.args[2]
        self.assertEqual(payload['thinking'],{'type':'disabled'})
        self.assertEqual(payload['max_tokens'],4096)

    def test_other_providers_do_not_receive_deepseek_parameters(self):
        with patch.object(ai_services,'request_json',return_value=self.response('{}')) as request:
            ai_services.complete(self.config('qwen'),'JSON',{})
        self.assertNotIn('thinking',request.call_args.args[2])

    def test_reasoning_exhaustion_has_specific_diagnostic(self):
        with patch.object(ai_services,'request_json',return_value=self.response(None,'length','private reasoning')):
            with self.assertRaisesRegex(ai_services.AIServiceError,'思考阶段耗尽输出额度') as error:
                ai_services.complete(self.config(),'JSON',{})
        self.assertNotIn('private reasoning',str(error.exception))

    def test_truncated_answer_is_rejected_even_if_json_parses(self):
        with patch.object(ai_services,'request_json',return_value=self.response('{}','length')):
            with self.assertRaisesRegex(ai_services.AIServiceError,'结果不完整'):
                ai_services.complete(self.config(),'JSON',{})

    def test_empty_reasoning_only_filtered_and_resource_responses(self):
        for response,diagnostic in [(self.response(''),'空回答'),
                                    (self.response(None,reasoning='private'),'只返回了思考内容'),
                                    (self.response(None,'content_filter'),'拦截'),
                                    (self.response(None,'insufficient_system_resource'),'计算资源不足')]:
            with self.subTest(diagnostic=diagnostic),patch.object(ai_services,'request_json',return_value=response):
                with self.assertRaisesRegex(ai_services.AIServiceError,diagnostic):
                    ai_services.complete(self.config(),'JSON',{})

    def test_missing_choices_has_structural_diagnostic(self):
        with patch.object(ai_services,'request_json',return_value={'choices':[]}):
            with self.assertRaisesRegex(ai_services.AIServiceError,'返回结构异常'):
                ai_services.complete(self.config(),'JSON',{})
