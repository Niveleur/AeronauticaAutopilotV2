"""Run the suite without hiding its exit status; expose CI failure tracebacks."""
import os
from pathlib import Path
import sys
import unittest


def main():
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0,str(root))
    suite = unittest.defaultTestLoader.discover(str(root/'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failures = result.failures + result.errors
    if os.getenv('GITHUB_ACTIONS') == 'true':
        def escape(value):
            return str(value).replace('%','%25').replace('\r','%0D').replace('\n','%0A')
        for test,details in failures:
            print(f'::error title={escape(test.id())}::{escape(details)}',flush=True)
        summary = os.getenv('GITHUB_STEP_SUMMARY')
        if summary:
            text = [f'GUI and detector tests: {result.testsRun} run, {len(failures)} failures/errors.\n']
            for test,details in failures:
                text.append(f'### {test.id()}\n\n```text\n{details}\n```\n')
            with Path(summary).open('a',encoding='utf-8') as output:
                output.write('\n'.join(text))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
