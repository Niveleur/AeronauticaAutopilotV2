import unittest
import numpy as np
from PIL import Image, ImageDraw
from AeroHelper.automation.aircraft_hud import analyze_cockpit, parse_instruments


def cockpit(slope=0., lines=(.53,), size=(1000,600)):
    image=Image.new('RGB',size,(15,35,70))
    draw=ImageDraw.Draw(image)
    w,h=size
    for y in lines:
        draw.line([(int(w*.08),y*h+slope*(w*.08-w/2)),
                   (int(w*.89),y*h+slope*(w*.89-w/2))], fill='white',width=3)
    return image


class GeometryTests(unittest.TestCase):
    def test_level_and_tilted_lines_at_multiple_resolutions(self):
        for size in ((640,480),(1000,600),(1920,1080)):
            for slope in (0.,.2,-.2):
                with self.subTest(size=size,slope=slope):
                    reading=analyze_cockpit(cockpit(slope,size=size))
                    self.assertIsNotNone(reading.horizon_y,reading.reason)
                    self.assertAlmostEqual(reading.horizon_y,size[1]*.53,delta=5)
                    self.assertAlmostEqual(reading.horizon_slope,slope,delta=.025)

    def test_blank_and_one_sided_lines_rejected(self):
        image=Image.new('RGB',(800,600),'black')
        self.assertIsNone(analyze_cockpit(image).horizon_y)
        ImageDraw.Draw(image).line((50,320,200,320),fill='white',width=3)
        self.assertIsNone(analyze_cockpit(image).horizon_y)

    def test_repeated_ladder_lines_are_ambiguous(self):
        reading=analyze_cockpit(cockpit(lines=(.45,.6)))
        self.assertIsNone(reading.horizon_y)
        self.assertIn('ambiguous',reading.reason)

    def test_coloured_scene_and_text_do_not_count_as_white_horizon(self):
        image=Image.new('RGB',(800,600),'black')
        draw=ImageDraw.Draw(image)
        draw.line((0,300,799,300),fill=(255,100,50),width=4)
        draw.text((100,340),'ALT 10000 FT',fill='white')
        draw.text((600,340),'IAS 150 KTS',fill='white')
        self.assertIsNone(analyze_cockpit(image).horizon_y)

    def test_invalid_or_small_images(self):
        with self.assertRaises(ValueError): analyze_cockpit(np.zeros((200,300)))
        self.assertIsNone(analyze_cockpit(Image.new('RGB',(100,100))).altitude_box)


class InstrumentTests(unittest.TestCase):
    def test_explicit_labels_and_units(self):
        values=parse_instruments('ALT: 12,500 FT\nIAS: 155 KTS')
        self.assertEqual(values['altitude'].value,12500)
        self.assertEqual(values['airspeed'].value,155)
        self.assertEqual(values['airspeed'].unit,'KTS')

    def test_unlabelled_or_unitless_digits_do_not_become_instruments(self):
        for text in ('12500 155','ALT 12500 IAS 155','HDG 125 ALTITUDE unknown'):
            self.assertTrue(all(x.value is None for x in parse_instruments(text).values()))

    def test_conflicts_and_out_of_range_values_rejected(self):
        self.assertIsNone(parse_instruments('ALT 1000 FT ALT 2000 FT')['altitude'].value)
        self.assertIsNone(parse_instruments('ALT 999999 FT')['altitude'].value)
        self.assertIsNone(parse_instruments('IAS -10 KTS')['airspeed'].value)


if __name__=='__main__': unittest.main()
