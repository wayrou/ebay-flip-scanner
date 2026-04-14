import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from rules import classify


class ClassifyTests(unittest.TestCase):
    def test_green_gpu_listing_is_detected(self):
        bucket, tags = classify("RTX 3080 boots in Windows but crashes under load after Furmark", "gpu")
        self.assertEqual(bucket, "GREEN")
        self.assertIn("alive", tags)

    def test_accessory_listing_is_rejected(self):
        bucket, tags = classify("RTX 3080 fan replacement bracket", "gpu")
        self.assertEqual(bucket, "RED")
        self.assertIn("accessory_or_part_only", tags)

    def test_graphing_calculator_profile_detects_screen_issue(self):
        bucket, tags = classify("TI-84 Plus CE turns on but has lines on screen", "graphing_calculator")
        self.assertEqual(bucket, "GREEN")
        self.assertIn("repairable_issue", tags)

    def test_graphing_calculator_no_power_is_not_green(self):
        bucket, tags = classify("TI-84 Plus Calculator For Parts Won’t Turn On", "graphing_calculator")
        self.assertEqual(bucket, "YELLOW")
        self.assertIn("repair_signal", tags)

    def test_headphone_profile_detects_broken_hinge(self):
        bucket, tags = classify("Sony WH-1000XM4 headphones hinge broken for parts", "premium_headphones")
        self.assertEqual(bucket, "YELLOW")
        self.assertIn("repair_signal", tags)

    def test_handheld_console_profile_detects_charge_issue(self):
        bucket, tags = classify("Nintendo Switch HAC-001 powers on but won't charge", "handheld_console")
        self.assertEqual(bucket, "GREEN")
        self.assertIn("repairable_issue", tags)

    def test_camera_lens_profile_detects_autofocus_issue(self):
        bucket, tags = classify("Canon EF 50mm f/1.8 STM lens autofocus not working for parts", "camera_lens")
        self.assertEqual(bucket, "YELLOW")
        self.assertIn("repair_signal", tags)

    def test_camera_lens_fungus_is_not_green(self):
        bucket, tags = classify("Sony E-Mount 55-210mm camera lens has fungus, parts/repair", "camera_lens")
        self.assertEqual(bucket, "RED")
        self.assertIn("damage_keyword", tags)


if __name__ == "__main__":
    unittest.main()
