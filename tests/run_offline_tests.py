"""Run all regression tests with isolated fake model configuration and blocked model transport."""
import unittest
import argparse
from pathlib import Path
from tests.offline_test_runtime import offline_models
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('suites',nargs='*');args=parser.parse_args()
    from courseagent.workspace_setup import initialize_workspace
    initialize_workspace(ROOT)
    with offline_models():
        suite=unittest.defaultTestLoader.loadTestsFromNames(args.suites) if args.suites else unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py',top_level_dir=str(ROOT))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
if __name__=='__main__':main()
