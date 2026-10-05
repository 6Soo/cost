import sys
import unittest
from types import ModuleType
from unittest.mock import Mock,patch
from webapp.google_oidc import GoogleAuthTokenVerifier
class ClockSkewTests(unittest.TestCase):
 def check_skew(self,skew):
  names=['google','google.oauth2','google.oauth2.id_token','google.auth','google.auth.transport','google.auth.transport.requests']
  modules={name:ModuleType(name) for name in names}
  verify=Mock(return_value={'sub':'synthetic'})
  modules['google.oauth2.id_token'].verify_oauth2_token=verify
  modules['google.auth.transport.requests'].Request=Mock()
  with patch.dict(sys.modules,modules):
   GoogleAuthTokenVerifier(client_id='synthetic',clock_skew=skew)._verify_with_library('synthetic-token','synthetic')
  self.assertEqual(verify.call_args.kwargs['clock_skew_in_seconds'],skew)
  self.assertEqual(verify.call_args.kwargs['audience'],'synthetic')
 def test_configured_skew_reaches_google_verification(self): self.check_skew(60)
 def test_zero_skew_remains_zero(self): self.check_skew(0)
