"""Dry-run only (outside the study): six 20-s tests, to exercise the chunk hard limit and resume."""
import time, unittest
import ddt
@ddt.ddt
class TestLong(unittest.TestCase):
    @ddt.data(1, 2, 3, 4, 5, 6)
    def test_sleep(self, i): time.sleep(20)
