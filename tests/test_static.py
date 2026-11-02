"""The front end has no build step, so check that everything the page points at actually exists."""
import re
import unittest
from pathlib import Path

from tests.helpers import demo_app

STATIC = Path(__file__).resolve().parent.parent / "weathervane" / "static"


class StaticAssetTests(unittest.TestCase):
    def setUp(self):
        self.c = demo_app().test_client()
        self.index = (STATIC / "index.html").read_text(encoding="utf-8")
        self.css = (STATIC / "css" / "styles.css").read_text(encoding="utf-8")

    def test_every_local_reference_in_index_exists(self):
        refs = re.findall(r'(?:href|src)="(/static/[^"]+)"', self.index)
        self.assertTrue(refs)
        for ref in refs:
            self.assertTrue((STATIC / ref[len("/static/"):]).is_file(), f"missing {ref}")
            self.assertEqual(self.c.get(ref).status_code, 200, ref)

    def test_every_font_file_in_css_exists(self):
        files = re.findall(r'url\("\.\./fonts/([^"]+)"\)', self.css)
        self.assertEqual(sorted(files), ["poppins-300.woff", "poppins-400.woff", "poppins-500.woff", "poppins-700.woff"])
        for name in files:
            self.assertTrue((STATIC / "fonts" / name).stat().st_size > 1000, name)

    def test_poppins_is_the_only_family_and_is_self_hosted(self):
        self.assertNotIn("fonts.googleapis.com", self.index)
        self.assertNotIn("Fraunces", self.css + self.index)
        self.assertNotIn("Figtree", self.css + self.index)
        self.assertIn('--font-display: "Poppins"', self.css)
        # only weights that ship with the bundled files (a 600 would silently render as 700)
        self.assertEqual(set(re.findall(r"font-weight:\s*(\d{3})", self.css)), {"300", "400", "500", "700"})

    def test_logo_is_in_header_and_favicon_route_works(self):
        self.assertIn('class="brand-mark"', self.index)
        r = self.c.get("/favicon.ico")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/static/img/favicon.ico"))

    def test_csp_allows_local_fonts_only(self):
        csp = self.c.get("/api/health").headers["Content-Security-Policy"]
        self.assertIn("font-src 'self';", csp)
        self.assertNotIn("googleapis", csp)


if __name__ == "__main__":
    unittest.main()
