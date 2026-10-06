import unittest
from backend.mail import translation as mail_translation
class TranslationLayoutTests(unittest.TestCase):
    def test_preserves_lists_links_images_tables_and_escapes_model_text(self):
        markup='<p>Hello &amp; welcome</p><ol start="2"><li><a href="https://box.example/a%20%E6%9C%88.pdf">Register here</a><img data-external="0" alt="Poster"></li></ol><table><tr><td>Date</td></tr></table>'
        template=mail_translation.Template(markup)
        self.assertEqual(template.texts,['Hello & welcome','Register here','Date'])
        result=template.render(['你好，欢迎','报名 <script>','日期'])
        self.assertEqual(result,markup.replace('Hello &amp; welcome','你好，欢迎').replace('Register here','报名 &lt;script&gt;').replace('Date','日期'))
        self.assertNotIn('%E6', ''.join(template.texts))

    def test_plain_text_line_order_whitespace_and_url_are_preserved(self):
        template=mail_translation.Template('<pre>First\n\n  Second\nhttps://example.test/a%20b\n</pre>')
        self.assertEqual(template.render(['第一行','第二行']),'<pre>第一行\n\n  第二行\nhttps://example.test/a%20b\n</pre>')

    def test_plain_text_link_is_clickable_not_percent_encoded_body_text(self):
        markup,external=mail_translation.source({'original':None,'source_body':'Register<https://example.test/%E6%9C%88.pdf>\nNext','body':''})
        template=mail_translation.Template(markup)
        self.assertEqual(template.texts,['Register','Next'])
        result=template.render(['报名','下一行'])
        self.assertIn('href="https://example.test/%E6%9C%88.pdf">报名</a>',result)
        self.assertEqual(external,[])

    def test_incomplete_response_is_not_rendered(self):
        template=mail_translation.Template('<p>First</p><p>Second</p>')
        with self.assertRaises(ValueError):template.render(['第一行'])

    def test_cache_uses_content_not_character_count(self):
        self.assertNotEqual(mail_translation.fingerprint('A','<p>A</p>'),mail_translation.fingerprint('A','<p>B</p>'))

    def test_batches_cover_every_segment(self):
        texts=['a'*4000,'b'*4000,'c']
        batches=list(mail_translation.batches(texts))
        self.assertEqual([item['text'] for batch in batches for item in batch],texts)
        self.assertEqual(len(batches),2)
