"""Build identity and dependency diagnostics, without importing NumPy."""
import json
from pathlib import Path
import sys


def build_revision():
    root = getattr(sys, '_MEIPASS', None)
    if root is None:
        return 'development'
    try:
        info = json.loads((Path(root) / 'build-info.json').read_text(encoding='utf-8-sig'))
        return str(info['commit'])[:7]
    except (OSError, ValueError, KeyError):
        return 'unknown'


def hud_failure_summary(exc):
    text = str(exc)
    if 'Original error was:' in text:
        root_error = text.rsplit('Original error was:', 1)[1].strip()
    else:
        root_error = text.strip()
    lines = [f'Build: {build_revision()}', f'{type(exc).__name__}: {root_error}']
    root = getattr(sys, '_MEIPASS', None)
    if root is not None:
        base = Path(root)
        dlls = list((base / 'numpy' / '.libs').glob('*openblas*.dll'))
        extensions = list((base / 'numpy' / 'core').glob('_multiarray_umath*.pyd'))
        lines.append('Bundled NumPy OpenBLAS DLL: ' + ('present' if dlls else 'MISSING'))
        lines.append('Bundled NumPy C extension: ' + ('present' if extensions else 'MISSING'))
    return '\n'.join(lines)
