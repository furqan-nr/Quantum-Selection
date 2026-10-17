"""Dry-run only (outside the study): exercises the runner's timeout and crash handling."""
import os, time, unittest
class TestSynthetic(unittest.TestCase):
    def test_a_ok(self): time.sleep(0.1)
    def test_b_hang(self): time.sleep(1000)
    def test_c_ok(self): time.sleep(0.1)
    def test_d_crash(self): os.abort()
    def test_e_fail(self): self.assertEqual(1, 2)
