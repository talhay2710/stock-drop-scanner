"""כותב יחיד לנתוני המשתמש: רק מחשב הבעלים (שבו יש config.yaml) דוחף לגיט; ענן ובודקים אף פעם. הרצה: python -m unittest tests.test_cloud_sync_guard -v"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import cloud_sync


class OnlyOwnerPushes(unittest.TestCase):
    def test_no_config_yaml_means_no_git_calls(self):
        with mock.patch.object(cloud_sync, "CONFIG_PATH", os.path.join(ROOT, "does_not_exist.yaml")), \
             mock.patch.object(cloud_sync, "_git_run") as git:
            self.assertEqual(cloud_sync.sync_to_cloud("x", include_db=True), "no_change")
            git.assert_not_called()

    def test_tester_mode_means_no_git_calls(self):
        with mock.patch.object(cloud_sync, "tester_mode", return_value=True), mock.patch.object(cloud_sync, "_git_run") as git:
            self.assertEqual(cloud_sync.sync_to_cloud("x", include_db=True), "no_change")
            git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
