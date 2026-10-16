"""Offline unit tests for the deterministic safety layer. No API key or credits needed:
    python -m unittest discover -s tests -v
"""
import sys, unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import knowledge as K


class Expiry(unittest.TestCase):
    def test_formats(self):
        for text, want in [("EXP 08/2026", (2026, 8)), ("Exp: AUG.2026", (2026, 8)), ("EXP 08-26", (2026, 8)),
                           ("Use before 11/2028", (2028, 11)), ("Expiry Date: 03/29", (2029, 3)),
                           ("EXP. DEC 2027 MRP 30", (2027, 12))]:
            self.assertEqual(K.parse_expiry(text), want, text)

    def test_missing(self):
        self.assertIsNone(K.parse_expiry("Mfg 01/2024 Batch A1"))
        self.assertEqual(K.expiry_verdict(None)["status"], "unknown")

    def test_verdicts(self):
        today = date(2026, 10, 16)
        self.assertEqual(K.expiry_verdict((2026, 9), today)["status"], "expired")
        self.assertEqual(K.expiry_verdict((2026, 10), today)["status"], "ok")  # valid through end of month
        self.assertEqual(K.expiry_verdict((2027, 1), today)["status"], "ok")
        self.assertNotIn("safe", K.expiry_verdict((2027, 1), today)["msg"].lower().replace("not safe", ""))


class RedFlags(unittest.TestCase):
    def test_trigger(self):
        for t in ["I have chest pain", "he fainted", "snake bite on leg", "took too many tablets", "मेरे सीने में दर्द है",
                  "saans nahi aa rahi", "நெஞ்சு வலி", "I want to kill myself", "heavy bleeding"]:
            self.assertTrue(K.is_red_flag(t), t)

    def test_no_false_alarm(self):
        for t in ["When should I take this tablet?", "Is paracetamol okay after food?", ""]:
            self.assertFalse(K.is_red_flag(t), t)


class Interactions(unittest.TestCase):
    def test_duplicate_and_pairs(self):
        w = K.check_list([{"name": "Crocin", "salts": ["paracetamol"]}, {"name": "Dolo", "salts": ["paracetamol"]}])
        self.assertEqual([x["type"] for x in w], ["duplicate"])
        w = K.check_list([{"name": "Voveran", "salts": ["diclofenac"]}, {"name": "Brufen", "salts": ["ibuprofen"]}])
        self.assertTrue(any(x["type"] == "interaction" for x in w))
        w = K.check_list([{"name": "A", "salts": ["warfarin"]}, {"name": "B", "salts": ["ibuprofen"]}])
        self.assertTrue(any("bleeding" in x["msg"] for x in w))

    def test_no_invented_warnings(self):
        self.assertEqual(K.check_list([{"name": "A", "salts": ["paracetamol"]}, {"name": "B", "salts": ["cetirizine"]}]), [])
        self.assertEqual(K.check_list([{"name": "A", "salts": []}, {"name": "B", "salts": []}]), [])


class ClassCards(unittest.TestCase):
    def test_cards(self):
        self.assertEqual(K.class_warnings_for(["azithromycin"])[0]["id"], "antibiotic")
        self.assertEqual(K.class_warnings_for(["diclofenac sodium"])[0]["id"], "nsaid")
        self.assertEqual(K.class_warnings_for(["paracetamol"]), [])

    def test_missing_details(self):
        self.assertEqual(K.missing_details("B.No. 12 Mfg Lic 5 MRP Rs 10 EXP 01/2030"), [])
        self.assertIn("batch number", K.missing_details("MRP Rs 10 EXP 01/2030 mfg by X"))


if __name__ == "__main__":
    unittest.main()
