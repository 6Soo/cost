import unittest
from unittest.mock import patch
from webapp import google_oidc as g
class PersistentSessionTests(unittest.TestCase):
 def setUp(self):
  self.cfg=g.OIDCConfig(client_id='synthetic',client_secret='synthetic',session_secret='Zq4Wm8Xb2Lt7Nv3Ks6Pd1Hg5Jc9Rf0Eu3Ti5Qo8Ny1Ab',public_base_url='https://example.test')
  self.adapter=g.GoogleOIDCAdapter(config=self.cfg,signer=g.SessionSigner('Zq4Wm8Xb2Lt7Nv3Ks6Pd1Hg5Jc9Rf0Eu3Ti5Qo8Ny1Ab'))
  with patch.object(g,'_now',return_value=100000):
   self.cookie=self.adapter.issue_cookie({'sub':'synthetic'},generation=3)
  self.headers={'Cookie':g.COOKIE_NAME+'='+self.cookie}
 def test_persists_after_eight_hours(self):
  with patch.object(g,'_now',return_value=100000+86400):
   self.assertIsNotNone(self.adapter.session_for(self.headers))
 def test_activity_renews_expiry(self):
  with patch.object(g,'_now',return_value=100000+86400):
   header=self.adapter.renewal_cookie_header(self.headers)
  value=header.split(';')[0].split('=',1)[1]
  payload=self.adapter.signer.verify(value)
  self.assertEqual(payload['exp'],100000+86400+self.cfg.session_ttl)
  self.assertEqual(payload['gen'],3)
  self.assertIn('Secure',header)
 def test_new_cookie_does_not_renew_on_every_poll(self):
  with patch.object(g,'_now',return_value=100100):
   self.assertIsNone(self.adapter.renewal_cookie_header(self.headers))
 def test_forged_cookie_cannot_renew(self):
  self.assertIsNone(self.adapter.renewal_cookie_header({'Cookie':g.COOKIE_NAME+'=invalid'}))


 def test_existing_short_session_is_upgraded(self):
  payload=self.adapter.signer.verify(self.cookie)
  payload['exp']=100000+28800
  headers={'Cookie':g.COOKIE_NAME+'='+self.adapter.signer.sign(payload)}
  with patch.object(g,'_now',return_value=100100):
   self.assertIsNotNone(self.adapter.renewal_cookie_header(headers))
