import json
import unittest

from gateway_adapters.huawei.native_script import selected_functions


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
