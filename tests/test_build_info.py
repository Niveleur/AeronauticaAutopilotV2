import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from AeroHelper.utils.build_info import build_revision, hud_failure_summary


class BuildDiagnosticsTests(unittest.TestCase):
    def test_numpy_original_error_is_visible_before_generic_help(self):
        exc = ImportError('IMPORTANT: Importing the numpy C-extensions failed.\n'
                          'Generic advice and troubleshooting link\n'
                          'Original error was: DLL load failed while importing _multiarray_umath: missing library')
        result = hud_failure_summary(exc)
        self.assertIn('DLL load failed while importing _multiarray_umath', result)
        self.assertNotIn('Generic advice', result)
        self.assertNotIn('IMPORTANT', result)

    def test_frozen_build_identifies_missing_then_present_dlls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'build-info.json').write_text(json.dumps({'commit': 'abcdef123456'}))
            with patch.object(sys, '_MEIPASS', directory, create=True):
                self.assertEqual(build_revision(), 'abcdef1')
                self.assertIn('OpenBLAS DLL: MISSING', hud_failure_summary(ImportError('missing')))
                dll = root / 'numpy' / '.libs' / 'libopenblas.dll'
                dll.parent.mkdir(parents=True)
                dll.touch()
                extension = root / 'numpy' / 'core' / '_multiarray_umath.cp311-win_amd64.pyd'
                extension.parent.mkdir()
                extension.touch()
                result = hud_failure_summary(ImportError('cannot load'))
                self.assertIn('OpenBLAS DLL: present', result)
                self.assertIn('C extension: present', result)
                self.assertIn('Build: abcdef1', result)

    def test_no_manifest_does_not_hide_original_failure(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys, '_MEIPASS', directory, create=True):
            self.assertEqual(build_revision(), 'unknown')
            self.assertIn('RuntimeError: test failure', hud_failure_summary(RuntimeError('test failure')))


if __name__ == '__main__':
    unittest.main()
