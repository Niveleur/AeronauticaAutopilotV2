import unittest
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from AeroHelper.automation.aircraft_hud import (analyze_cockpit, parse_instruments,
                                                parse_tape_readout, tape_digit_boxes,
                                                reconcile_instruments)


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

    def test_whiteout_and_broad_bright_edges_are_not_hud_lines(self):
        for colour in ('white', (225,225,225)):
            image = Image.new('RGB', (1000,600), colour)
            self.assertIsNone(analyze_cockpit(image).horizon_y)
        image = Image.new('RGB', (1000,600), (80,110,150))
        ImageDraw.Draw(image).rectangle((0,330,999,599), fill='white')
        self.assertIsNone(analyze_cockpit(image).horizon_y)

    def test_thin_hud_line_survives_bright_scenery(self):
        image = Image.new('RGB', (1000,600), (220,220,220))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0,400,999,599), fill='white')
        draw.line((80,318,890,318), fill='white', width=3)
        reading = analyze_cockpit(image)
        self.assertAlmostEqual(reading.horizon_y,318,delta=5)
        # A fully washed out line has no measurable contrast: fail closed.
        draw.rectangle((0,0,999,599), fill='white')
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


class ActualCaptureTests(unittest.TestCase):
    # Cropped central HUD only: no chat, player roster or other user identifiers.
    fixture = Path(__file__).parent / 'fixtures' / 'aircraft-tapes-29841ft-89kt.png'

    def test_real_hud_horizon_and_tape_crops_at_multiple_scales(self):
        with Image.open(self.fixture) as original:
            for scale in (.5,1.,1.5):
                with self.subTest(scale=scale):
                    image = original.resize((int(original.width*scale),int(original.height*scale)))
                    reading = analyze_cockpit(image)
                    self.assertIsNotNone(reading.tape_rails)
                    self.assertAlmostEqual(reading.horizon_y,533*scale,delta=6)
                    self.assertAlmostEqual(reading.horizon_slope,0.,delta=.02)
                    # Crops track the central readouts rather than the sky.
                    altitude,speed = reading.altitude_box,reading.speed_box
                    self.assertTrue(altitude[0] < 1220*scale < altitude[2])
                    self.assertTrue(speed[0] < 210*scale < speed[2])
                    for box in tape_digit_boxes(reading).values():
                        self.assertTrue(box[1] < 457*scale < box[3])

    def test_snow_capture_tracks_hud_instead_of_terrain(self):
        fixture = self.fixture.with_name('aircraft-tapes-snow-2639ft-156kt.png')
        with Image.open(fixture) as source:
            for scale in (.5,1.,1.5):
                with self.subTest(scale=scale):
                    image = source.resize((round(source.width*scale),round(source.height*scale)))
                    reading = analyze_cockpit(image)
                    self.assertIsNotNone(reading.tape_rails)
                    self.assertIsNotNone(reading.altitude_box)
                    self.assertAlmostEqual(reading.horizon_y,601*scale,delta=6)
                    self.assertAlmostEqual(reading.horizon_slope,0.,delta=.02)

    def test_ultrawide_capture_uses_hud_rails_not_screen_edge_fractions(self):
        with Image.open(self.fixture) as crop:
            image=Image.new('RGB',(3440,1440),(80,90,110))
            image.paste(crop,(1000,300))
        reading=analyze_cockpit(image)
        self.assertAlmostEqual(reading.horizon_y,833,delta=5)
        self.assertTrue(2170 < reading.altitude_box[0] < 2190)
        self.assertTrue(1140 < reading.speed_box[0] < 1170)

    def test_missing_tape_does_not_produce_guessed_regions(self):
        with Image.open(self.fixture) as source:
            image=source.copy()
        ImageDraw.Draw(image).rectangle((1080,100,1110,800),fill='black')
        reading=analyze_cockpit(image)
        self.assertIsNone(reading.altitude_box)
        self.assertIsNone(reading.speed_box)

    def test_isolated_readouts_require_labels_and_consistency(self):
        altitude=parse_tape_readout('altitude','ALT 00 29841','29841 29841')
        speed=parse_tape_readout('airspeed','SPEED 089','089')
        self.assertEqual((altitude.value,altitude.unit),(29841,'FT'))
        self.assertEqual((speed.value,speed.unit),(89,'KTS'))
        self.assertIn('assumed',speed.reason)
        for label,text in [('GS 87','087'),('SPEED','089 088'),('SPEED','O89'),('SPEED','SPEED 89'),('VERTICAL SPEED','89')]:
            self.assertIsNone(parse_tape_readout('airspeed',label,text).value)

    def test_conflicting_full_screen_value_is_not_silently_overridden(self):
        full=parse_instruments('IAS 9 KTS')
        result=reconcile_instruments(full,{'airspeed':parse_tape_readout('airspeed','SPEED','089')})
        self.assertIsNone(result['airspeed'].value)
        self.assertIn('disagree',result['airspeed'].reason)

    def test_occluded_label_requires_independent_exact_value_confirmation(self):
        reading=parse_tape_readout('altitude','AT','29659',full_text='ALTITUDE 29659 VERTICAL SPEED 0.1 ft/s')
        self.assertEqual(reading.value,29659)
        self.assertIn('confirmed',reading.reason)
        for full in ('','29659','ALT 29659','ALTITUDE 2965','ALTITUDE 29659 ALTITUDE 29658'):
            self.assertIsNone(parse_tape_readout('altitude','AT','29659',full_text=full).value)

    def test_night_hud_keeps_geometry_and_readout_regions(self):
        fixture=self.fixture.with_name('aircraft-tapes-night-29659ft-88kt.png')
        with Image.open(fixture) as image:
            reading=analyze_cockpit(image)
        self.assertIsNotNone(reading.tape_rails)
        self.assertAlmostEqual(reading.horizon_y,536,delta=5)
        self.assertAlmostEqual(reading.horizon_slope,0.,delta=.02)
        self.assertTrue(reading.altitude_box[0] < 1220 < reading.altitude_box[2])

    def test_unit_aliases_do_not_create_false_source_disagreements(self):
        full=parse_instruments('AIRSPEED 89 Knots IAS 89 KTS ALT 29841 FEET')
        tape={'airspeed':parse_tape_readout('airspeed','SPEED','089'),
              'altitude':parse_tape_readout('altitude','ALT','29841')}
        combined=reconcile_instruments(full,tape)
        self.assertEqual(combined['airspeed'].value,89)
        self.assertEqual(combined['altitude'].value,29841)

    def test_explicit_units_before_altitude_value(self):
        self.assertEqual(parse_instruments('ALTITUDE ft 2040')['altitude'].value,2040)


if __name__=='__main__': unittest.main()
