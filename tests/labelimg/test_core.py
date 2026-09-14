"""Run LabelImg Master's offline self-test as a script or under pytest."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fluxbox.apps.labelimg.selftest import run_selftest


def test_core():
    assert run_selftest(verbose=False) == 0


if __name__ == "__main__":
    sys.exit(run_selftest())
