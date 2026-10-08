import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from backend.cloud import NoEmailRedirect, send_auth_email


class EmailDeliveryTests(unittest.TestCase):
    def test_https_delivery_uses_configured_sender_and_exact_recipient(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"id":"email-id"}'
        with patch.dict(os.environ, {'RESEND_API_KEY': 'test-secret', 'MAIL_FROM': 'TimeMate <noreply@timemate.cc>'}), patch('backend.cloud.build_opener') as opener:
            opener.return_value.open.return_value = response
            send_auth_email('user@example.com', '123456', 'TimeMate 注册验证码', '注册')
        req = opener.return_value.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://api.resend.com/emails')
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Authorization'), 'Bearer test-secret')
        payload = json.loads(req.data)
        self.assertEqual(payload['to'], ['user@example.com'])
        self.assertEqual(payload['from'], 'TimeMate <noreply@timemate.cc>')
        self.assertIn('123456', payload['text'])
        self.assertIsInstance(opener.call_args.args[0], NoEmailRedirect)
        self.assertIsNone(NoEmailRedirect().redirect_request(req, None, 302, '', {}, 'https://elsewhere.example'))

    def test_failures_do_not_expose_provider_body_or_api_key(self):
        failures = [
            HTTPError('https://api.resend.com/emails', 403, 'Forbidden', {}, io.BytesIO(b'{"name":"validation_error","message":"test-secret private@example.com"}')),
            URLError('test-secret'),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.dict(os.environ, {'RESEND_API_KEY': 'test-secret'}), patch('backend.cloud.build_opener') as opener, self.assertLogs('backend.cloud', 'WARNING') as logs:
                opener.return_value.open.side_effect = failure
                with self.assertRaises(ValueError) as raised:
                    send_auth_email('user@example.com', '123456', '验证码', '注册')
            self.assertNotIn('test-secret', str(raised.exception) + str(logs.output))
            self.assertNotIn('private@example.com', str(raised.exception) + str(logs.output))

    def test_missing_configuration_never_attempts_delivery(self):
        with patch.dict(os.environ, {'RESEND_API_KEY': ''}), patch('backend.cloud.build_opener') as opener:
            with self.assertRaisesRegex(ValueError, '尚未配置'):
                send_auth_email('user@example.com', '123456', '验证码', '注册')
            opener.assert_not_called()

    def test_invalid_or_unacknowledged_response_is_failure(self):
        for body in (b'<html>Error</html>', b'{}', b'[]'):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = body
            with self.subTest(body=body), patch.dict(os.environ, {'RESEND_API_KEY': 'test-secret'}), patch('backend.cloud.build_opener') as opener:
                opener.return_value.open.return_value = response
                with self.assertRaisesRegex(ValueError, '发送失败'):
                    send_auth_email('user@example.com', '123456', '验证码', '注册')
