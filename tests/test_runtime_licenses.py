import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import runtime_bundle


class RuntimeLicenseTests(unittest.TestCase):
    def test_build_helpers_and_third_party_notices_are_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'node_modules/helper'
            source.mkdir(parents=True)
            (root / 'package-lock.json').write_text(json.dumps({'packages': {
                'node_modules/helper': {'version': '1.0', 'dev': True},
                'node_modules/other-platform': {'version': '1.0', 'dev': True, 'optional': True},
            }}))
            (source / 'package.json').write_text(json.dumps({'version': '1.0', 'license': 'MIT'}))
            (source / 'LICENSE').write_text('upstream copyright and permission')
            (source / 'THIRD-PARTY-LICENSE').write_text('injected helper attribution')
            (source / 'ThirdPartyNoticeText.txt').write_text('additional notice')
            output = root / 'bundle'
            output.mkdir()
            with patch.object(runtime_bundle, 'PROJECT', root):
                runtime_bundle.collect_frontend_licenses(output)
                records = json.loads((output / 'licenses/frontend-dependencies.json').read_text())
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['license'], 'MIT')
                self.assertEqual(len(records[0]['files']), 3)
                for name in records[0]['files']:
                    self.assertTrue((output / name).is_file())
                (source / 'LICENSE').unlink()
                (source / 'THIRD-PARTY-LICENSE').unlink()
                (source / 'ThirdPartyNoticeText.txt').unlink()
                with self.assertRaisesRegex(RuntimeError, 'license identifier or text missing'):
                    runtime_bundle.collect_frontend_licenses(output)

    def test_runtime_copy_excludes_unused_profiler_assets_and_gui_binaries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'runtime'
            for name in ('Lib/profiling/sampling/_vendor/d3.js', 'Lib/json/__init__.py',
                         'DLLs/_tkinter.pyd', 'DLLs/tcl90.dll', 'DLLs/_ssl.pyd'):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            destination = root / 'copy'
            runtime_bundle.copy_tree(source, destination,
                runtime_bundle.OMIT_STDLIB_DIRS | runtime_bundle.OMIT_RUNTIME_FILES)
            self.assertEqual({p.relative_to(destination).as_posix() for p in destination.rglob('*') if p.is_file()},
                             {'Lib/json/__init__.py', 'DLLs/_ssl.pyd'})
