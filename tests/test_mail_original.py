import unittest
from email.message import EmailMessage

from backend.mail import original as mail_original
class OriginalMailTests(unittest.TestCase):
    def test_keeps_email_table_layout_and_inline_cid_image(self):
        message = EmailMessage()
        message.set_content('plain fallback')
        message.add_alternative(
            '<table style="border-collapse:collapse"><tr><td colspan="2">第一列</td></tr>'
            '<tr><td><img src="cid:Logo@School" width="24" alt="校徽"></td><td>公告</td></tr></table>',
            subtype='html',
        )
        message.get_payload()[-1].add_related(
            b'fake-png-content', maintype='image', subtype='png', cid='<logo@school>'
        )
        result = mail_original.extract(message, 'plain fallback')
        self.assertIn('<table style="border-collapse:collapse">', result['html'])
        self.assertIn('colspan="2"', result['html'])
        self.assertIn('data:image/png;base64,', result['html'])
        self.assertIn('width="24"', result['html'])
        self.assertEqual(result['external'], [])


if __name__ == '__main__':
    unittest.main()
