"""The watcher's interval setting. Run: python3 -m unittest discover tests"""
import importlib.util
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "claude_cache_timer.py")
spec = importlib.util.spec_from_file_location("cct_watch", SCRIPT)
cct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cct)


class WatchSeconds(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        cct.CONFIG_DIR = self.dir

    def write(self, text):
        with open(os.path.join(self.dir, "watch_seconds"), "w") as f:
            f.write(text)

    def test_default_without_a_config_dir_or_file(self):
        cct.CONFIG_DIR = None
        self.assertEqual(cct.watch_seconds(), cct.WATCH_SECONDS)
        cct.CONFIG_DIR = self.dir
        self.assertEqual(cct.watch_seconds(), cct.WATCH_SECONDS)

    def test_reads_the_file(self):
        self.write("10\n")
        self.assertEqual(cct.watch_seconds(), 10.0)
        self.write(" 2.5 ")
        self.assertEqual(cct.watch_seconds(), 2.5)

    def test_nonsense_and_too_small_keep_the_default(self):
        self.write("fast")
        self.assertEqual(cct.watch_seconds(), cct.WATCH_SECONDS)
        self.write("0")
        self.assertEqual(cct.watch_seconds(), cct.WATCH_SECONDS)


if __name__ == "__main__":
    unittest.main()
