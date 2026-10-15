"""Run package tests in Hermes' Python test environment; no model calls."""
import importlib.util
import sys
import unittest
from pathlib import Path
root=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('package', root/'__init__.py', submodule_search_locations=[str(root)])
package=importlib.util.module_from_spec(spec)
sys.modules['package']=package
spec.loader.exec_module(package)
suite=unittest.defaultTestLoader.loadTestsFromNames(['package.'+p.stem for p in sorted(root.glob('test_*.py'))])
raise SystemExit(not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful())
