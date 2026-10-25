"""Cleaning a report of personal details, for Windows and macOS paths on any OS."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arc2zen.diagnostics import Sanitizer  # noqa: E402

WINDOWS_ENV = {
    "USERNAME": "jdoe",
    "COMPUTERNAME": "DESKTOP-JM6GE8S",
    "USERDOMAIN": "CONTOSO",
    "USERDNSDOMAIN": "corp.contoso.com",
    "APPDATA": r"\\fileserver\profiles$\jdoe\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\jdoe\AppData\Local",
    "TEMP": r"C:\Users\JDOE~1\AppData\Local\Temp",
    "OneDrive": r"D:\OneDrive - Contoso Ltd",
}


def windows() -> Sanitizer:
    return Sanitizer.for_this_computer(
        space_names=["Side project", "Work", "Default"], profile_names=["Some profile 2", "Profile 1"],
        env=WINDOWS_ENV, home=r"C:\Users\jdoe", user="jdoe", computer="DESKTOP-JM6GE8S")


def mac() -> Sanitizer:
    return Sanitizer.for_this_computer(env={"USER": "jdoe"}, home="/Users/jdoe", user="jdoe", computer="Janes-MacBook")


class WindowsPaths(unittest.TestCase):
    def check(self, text: str, expected: str) -> None:
        cleaned = windows().clean(text)
        self.assertEqual(cleaned, expected)
        self.assertEqual(windows().leaks(cleaned), [])

    def test_backslashes(self):
        self.check(r"C:\Users\jdoe\AppData\Local\Arc", r"~\AppData\Local\Arc")

    def test_doubled_backslashes_in_an_error(self):
        self.check(r"Permission denied: 'C:\\Users\\jdoe\\AppData\\Local\\x.log'", r"Permission denied: '~\\AppData\\Local\\x.log'")

    def test_forward_slashes_and_case(self):
        self.check("c:/users/JDOE/AppData", "~/AppData")

    def test_long_path_prefix(self):
        self.check(r"\\?\C:\Users\jdoe\file", r"~\file")

    def test_file_url_and_url_encoding(self):
        self.check("file:///C:/Users/jdoe/My%20Files", "file:///~/My%20Files")
        self.check("C%3A%5CUsers%5Cjdoe%5Cx", "C%3A%5CUsers%5C<user>%5Cx")

    def test_short_name(self):
        self.check(r"C:\Users\JDOE~1\AppData\Local\Temp\arc-to-zen-1", r"%TEMP%\arc-to-zen-1")

    def test_folder_on_a_network_share(self):
        self.check(r"\\fileserver\profiles$\jdoe\AppData\Roaming\zen\Profiles", r"%APPDATA%\zen\Profiles")

    def test_onedrive_organisation(self):
        self.check(r"D:\OneDrive - Contoso Ltd\Desktop", r"%ONEDRIVE%\Desktop")
        self.check(r"E:\Sync\OneDrive - Contoso Ltd\x", r"E:\Sync\OneDrive\x")

    def test_a_name_that_only_starts_like_the_user(self):
        self.check(r"C:\Users\jdoe2\x", r"C:\Users\jdoe2\x")

    def test_names_outside_paths(self):
        self.check(r"Signed in as CONTOSO\jdoe on DESKTOP-JM6GE8S", r"Signed in as <domain>\<user> on <computer>")
        self.check("jdoe@corp.contoso.com", "<email>")

    def test_sid(self):
        self.check("owner S-1-5-21-3623811015-3361044348-30300820-1013", "owner <SID>")


class Everywhere(unittest.TestCase):
    def test_mac_home(self):
        self.assertEqual(mac().clean("/Users/jdoe/Library/Application Support/Arc"), "~/Library/Application Support/Arc")

    def test_urls_keep_only_the_site(self):
        self.assertEqual(mac().clean("tab https://user:secret@mail.example.com/inbox?token=abc kept"),
                         "tab https://mail.example.com kept")
        self.assertEqual(mac().clean("arc://history/ about:blank"), "arc://history/ about:blank")

    def test_space_and_profile_names(self):
        cleaned = windows().clean("Space Side project in Some profile 2; Work and Default; Profile 1")
        self.assertEqual(cleaned, "Space <space 1> in <profile 1>; <space 2> and Default; Profile 1")

    def test_leaks_are_found(self):
        self.assertTrue(windows().leaks(r"C:\Users\jdoe\x"))
        self.assertTrue(windows().leaks("on DESKTOP-JM6GE8S"))


if __name__ == "__main__":
    unittest.main()
