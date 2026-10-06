import unittest

from backend import app
class EventExtractionTests(unittest.TestCase):
    def test_weekly_timetable_notice_is_not_an_all_day_event(self):
        event = {
            'title': 'CSI101 Week 4 实验课',
            'start': '2026-10-05T00:00:00',
            'end': '2026-10-10T00:00:00',
            'kind': '活动',
            'allDay': True,
        }
        source = (
            'Please note that your lab will officially begin this week. '
            'Please check your timetable and go to the correct lab. '
            'Section: Week 4 | October 5th-9th'
        )
        self.assertEqual(app.normalize_events([event], source), [])

    def test_specific_class_meeting_is_preserved(self):
        event = {
            'title': 'CSI101 Week 4 实验课',
            'start': '2026-10-07T14:00:00',
            'end': '2026-10-07T16:00:00',
            'kind': '活动',
            'allDay': False,
        }
        source = 'CSI101 lab: Wednesday October 7, 14:00-16:00. Check your timetable for the room.'
        self.assertEqual(len(app.normalize_events([event], source)), 1)


if __name__ == '__main__':
    unittest.main()
