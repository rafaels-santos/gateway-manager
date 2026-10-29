import json
import unittest
from unittest.mock import Mock

from gateway_adapters.errors import GatewayError
from gateway_adapters.huawei.integration_report import integration_report, selected_functions


class ReportTests(unittest.TestCase):
    def test_only_whitelisted_complete_functions_escape_not_runtime_arrays(self):
        source = '''var privateKey="MUST_NOT_ESCAPE";
function AddSubmitParamChannel(Form) {
  // a comment with }
  var path="set.cgi?y=/radio";
  if (true) { Form.addParameter('y.Channel', '36'); }
}
var pageToken="MUST_NOT_ESCAPE";
function Other(){return pageToken;}
'''
        result = selected_functions(source, ('AddSubmitParamChannel',))
        self.assertIn('y.Channel', result['AddSubmitParamChannel'])
        self.assertNotIn('MUST_NOT_ESCAPE', json.dumps(result))
        self.assertNotIn('Other', json.dumps(result))

    def test_ambiguous_regex_and_credentials_are_omitted(self):
        for source in ("function AddSubmitParam(x){return /{/.test(x);}\nvar key='SECRET';",
                       "function AddSubmitParam(x){var secret='SECRET';}",
                       'function AddSubmitParam(x){new stPreSharedKey("SECRET");}',
                       'function AddSubmitParam(x){'):
            self.assertEqual(selected_functions(source, ('AddSubmitParam',)), {})

    def test_read_failure_is_reported_without_error_body_and_no_write(self):
        gateway = Mock(model_id='huawei-eg8145x6-10', identity={})
        gateway.request.side_effect = [GatewayError('sensitive response body'), 'function CheckConfigChannel(){return true;}', '']
        result = integration_report(gateway)
        self.assertTrue(result['read_only'])
        self.assertEqual(result['sources'][0]['status'], 'unavailable')
        self.assertIn('CheckConfigChannel', result['sources'][1]['functions'])
        self.assertNotIn('sensitive response body', json.dumps(result))
        self.assertTrue(all(len(call.args) == 1 for call in gateway.request.call_args_list))
