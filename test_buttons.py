import unittest

from buttons import (
    BUTTON_ACTIONS,
    DEFAULT_MAP,
    ButtonInput,
    button_for_key,
    button_label,
    clean_map,
)


class ButtonTests(unittest.TestCase):
    def test_key_names(self):
        self.assertEqual(button_for_key("[1]"), "keypad 1")
        self.assertEqual(button_for_key("[+]"), "keypad +")
        self.assertEqual(button_for_key("enter"), "keypad enter")
        self.assertEqual(button_for_key("f14"), "F14")
        for regular in ("1", "a", "return", "space", "[", "f1"):
            self.assertIsNone(button_for_key(regular), regular)

    def test_labels(self):
        self.assertEqual(button_label("keypad 1"), "Keypad 1")
        self.assertEqual(button_label("3"), "Button 3")
        self.assertEqual(button_label("F13"), "F13")

    def test_clean_map(self):
        self.assertEqual(clean_map(None), DEFAULT_MAP)
        self.assertEqual(clean_map({"1": "erupt_volcano", "2": "bogus", "3": 4, "4": "none"}),
                         {"1": "erupt_volcano"})

    def test_press_becomes_command(self):
        b = ButtonInput({"keypad 1": "dunebox_water", "2": "sea_up"})
        b.press("keypad 1")
        b.press("2")
        b.press("9")  # unmapped: remembered, no command
        cmds = b.poll()
        self.assertEqual([c["action"] for c in cmds], ["toggle_water", "nudge_sea_level"])
        self.assertEqual(cmds[0]["target"], "dunebox")
        self.assertEqual(cmds[0]["source"], "button")
        self.assertEqual(cmds[1]["value"], 0.02)
        self.assertEqual(b.poll(), [])
        ids = [x["id"] for x in b.status()["buttons"]]
        self.assertEqual(ids, ["2", "9", "keypad 1"])

    def test_set_mapping(self):
        b = ButtonInput({})
        self.assertTrue(b.set_mapping("F13", "erupt_volcano"))
        self.assertEqual(b.mapping, {"F13": "erupt_volcano"})
        self.assertTrue(b.set_mapping("F13", "none"))
        self.assertEqual(b.mapping, {})
        self.assertFalse(b.set_mapping("F13", "format_disk"))

    def test_every_action_has_a_label(self):
        for key, (label, command) in BUTTON_ACTIONS.items():
            self.assertTrue(label, key)
            if key != "none":
                self.assertIn("action", command)


if __name__ == "__main__":
    unittest.main()
