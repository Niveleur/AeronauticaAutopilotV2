import unittest
from AeroHelper.automation.aircraft_hud import (InstrumentCandidate,assess_altitude,
    parse_side_panel_altitude,side_panel_altitude_box)


def ft(value):
    return InstrumentCandidate(value,'FT' if value is not None else None,'test source')


class AltitudeBackupTests(unittest.TestCase):
    def test_zero_through_five_feet_agree_and_keep_cockpit_measurement(self):
        for delta in (0,1,-1,5,-5):
            result=assess_altitude(ft(29659),ft(29659+delta))
            self.assertEqual(result.status,'agree')
            self.assertEqual(result.difference_ft,abs(delta))
            self.assertEqual(result.selected.value,29659)
            self.assertEqual(result.tolerance_ft,5)

    def test_just_over_five_feet_rejects_both_instead_of_averaging(self):
        for delta in (5.01,-5.01,500):
            result=assess_altitude(ft(29659),ft(29659+delta))
            self.assertEqual(result.status,'disagree')
            self.assertIsNone(result.selected.value)
            self.assertIn('disagreement',result.selected.reason)

    def test_missing_cockpit_uses_explicit_unconfirmed_panel_fallback(self):
        result=assess_altitude(ft(None),ft(29659))
        self.assertEqual(result.status,'side_panel_fallback')
        self.assertEqual(result.selected.value,29659)
        self.assertIn('not cross-checked',result.selected.reason)

    def test_missing_panel_keeps_explicit_unconfirmed_cockpit(self):
        result=assess_altitude(ft(29659),ft(None))
        self.assertEqual(result.status,'cockpit_only')
        self.assertEqual(result.selected.value,29659)
        self.assertIsNone(result.difference_ft)

    def test_no_sources_is_unavailable_and_zero_altitude_is_valid(self):
        self.assertIsNone(assess_altitude(ft(None),ft(None)).selected.value)
        self.assertEqual(assess_altitude(ft(0),ft(0)).status,'agree')

    def test_units_nonfinite_values_and_invalid_tolerance(self):
        for reading in (InstrumentCandidate(100,'M','metres'),ft(float('nan')),ft(float('inf'))):
            self.assertEqual(assess_altitude(reading,ft(29659)).status,'side_panel_fallback')
        for tolerance in (-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): assess_altitude(ft(1),ft(1),tolerance)

    def test_panel_parser_requires_its_own_label_and_feet_unit(self):
        for text in ('ALTITUDE 29,659 ft VERTICAL SPEED 0.1 ft/s','ALTITUDE ft 29659'):
            self.assertEqual(parse_side_panel_altitude(text).value,29659)
        for text in ('29659','ALT 29659 ft','ALTITUDE 29659','ALTITUDE 29659 M',
                     'ALTITUDE 29659 ft ALTITUDE 29650 ft','VERTICAL SPEED 29659 ft/s'):
            self.assertIsNone(parse_side_panel_altitude(text).value)

    def test_region_is_separate_from_central_hud_and_exists_without_tapes(self):
        box=side_panel_altitude_box((3440,1440))
        self.assertLess(box[2],1000)
        self.assertLess(box[1],822)
        self.assertGreater(box[3],879)
        self.assertIsNone(side_panel_altitude_box((100,100)))


if __name__=='__main__': unittest.main()
