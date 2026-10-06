import json
import unittest

import app
import mail_dates


class MailDateTests(unittest.TestCase):
    def test_chinese_forwarded_time_overrides_outer_time(self):
        row={'date':'Mon, 05 Oct 2026 02:17:00 +0000',
             'source_body':'发件人: Kok Hoe Wong <kh.wong@xjtlu.edu.cn>\n发送时间: 2026年10月4日 16:32\n收件人: Student\n主题: 实验课'}
        self.assertEqual(app.mail_effective_date(row).isoformat(timespec='minutes'),'2026-10-04T16:32+08:00')

    def test_english_outlook_and_rfc_headers(self):
        for text,expected in [
            ('From: Teacher\nSent: Sunday, October 4, 2026 4:32 PM\nTo: Student','2026-10-04T16:32+08:00'),
            ('From: Teacher\nDate: Sun, 04 Oct 2026 08:32:45 +0000\nSubject: Notice','2026-10-04T08:32+00:00'),
            ('> 发件人：老师\n> 发送时间：2026年10月4日 星期日 下午4:32\n> 主题：通知','2026-10-04T16:32+08:00'),
        ]:
            with self.subTest(text=text):
                self.assertEqual(mail_dates.forwarded_date(text).isoformat(timespec='minutes'),expected)

    def test_sort_uses_original_time_not_forward_arrival(self):
        first={'date':'Mon, 05 Oct 2026 18:00:00 +0800','created':2,
               'body':'From: School\nSent: October 4, 2026 4:32 PM\nSubject: Older'}
        second={'date':'Mon, 05 Oct 2026 10:00:00 +0800','created':1,
                'body':'From: School\nSent: October 5, 2026 9:00 AM\nSubject: Newer'}
        self.assertLess(app.mail_sort_timestamp(first),app.mail_sort_timestamp(second))

    def test_existing_html_only_mail_is_supported(self):
        row={'date':'Mon, 05 Oct 2026 18:00:00 +0800','body':'flattened text',
             'original':json.dumps({'html':'<div><b>From:</b> School</div><div><b>Sent:</b> October 4, 2026 4:32 PM</div><div>Subject: Notice</div>'})}
        self.assertEqual(app.mail_effective_date(row).isoformat(timespec='minutes'),'2026-10-04T16:32+08:00')

    def test_activity_date_and_invalid_header_do_not_replace_mail_date(self):
        for body in ['活动时间：2026-10-15 13:30\n截止时间：2026-10-14 23:59',
                     'Date: October 15, 2026 1:30 PM\n活动地点：学校',
                     'From: Teacher\nSent: 2026年99月99日 25:99']:
            with self.subTest(body=body):
                row={'body':body,'date':'Mon, 05 Oct 2026 10:00:39 +0800'}
                self.assertEqual(app.mail_effective_date(row).isoformat(timespec='minutes'),'2026-10-05T10:00+08:00')

    def test_no_time_zone_in_forward_uses_school_time_zone(self):
        value=mail_dates.forwarded_date('From: Teacher\nSent: 2026/10/04 16:32')
        self.assertEqual(value.utcoffset().total_seconds(),8*3600)
