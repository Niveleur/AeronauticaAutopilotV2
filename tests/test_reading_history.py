import unittest
from AeroHelper.automation.reading_history import ReadingHistory


def readings(altitude=16000,speed=166):
    return {'altitude':{'value':altitude,'unit':'FT'},'airspeed':{'value':speed,'unit':'KTS'}}


class HistoryTests(unittest.TestCase):
    def test_dives_allowed_and_spikes_flagged_without_replacing_raw_values(self):
        history=ReadingHistory()
        history.assess(readings(),0)
        normal=history.assess(readings(15500,170),2)
        self.assertEqual(normal['altitude']['status'],'consistent')
        jump=history.assess(readings(75500,770),4)
        self.assertEqual(jump['altitude']['status'],'suspicious_jump')
        self.assertEqual(jump['altitude']['value'],75500)
        self.assertEqual(jump['airspeed']['status'],'suspicious_jump')
        recovered=history.assess(readings(15490,169),6)
        self.assertEqual(recovered['altitude']['status'],'consistent')
        self.assertFalse(recovered['altitude']['controls_enabled'])

    def test_missing_delayed_and_focus_gaps_do_not_reuse_old_readings(self):
        history=ReadingHistory()
        history.assess(readings(),0)
        missing=history.assess(readings(None,None),2)
        self.assertIsNone(missing['altitude']['value'])
        self.assertEqual(missing['altitude']['status'],'unavailable')
        delayed=history.assess(readings(50000),4,processing_seconds=8)
        self.assertEqual(delayed['altitude']['status'],'delayed')
        self.assertEqual(history.assess(readings(),6)['altitude']['status'],'consistent')
        self.assertEqual(history.assess(readings(50000),20)['altitude']['status'],'reacquired')

    def test_duplicate_timestamps_and_units_do_not_produce_rates(self):
        history=ReadingHistory()
        history.assess(readings(),1)
        self.assertEqual(history.assess(readings(),1)['altitude']['status'],'incomparable')
        candidate=readings();candidate['altitude']['unit']='M'
        self.assertEqual(history.assess(candidate,2)['altitude']['status'],'incomparable')
