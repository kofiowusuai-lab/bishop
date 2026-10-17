import re
import unittest
from bishop_runtime.identity import emblem

class IdentityTests(unittest.TestCase):
    def test_dimensions(self):
        for width, height in [(24,23),(16,18),(32,28)]:
            lines=emblem(width,height)
            self.assertEqual(len(lines),height)
            self.assertTrue(all(len(line)==width for line in lines))
            self.assertTrue(all(ch==' ' or '\u2800'<=ch<='\u28ff' for line in lines for ch in line))
    def test_colour_preserves_geometry(self):
        self.assertEqual([re.sub(r'\x1b\[[0-9;]*m','',line) for line in emblem(color=True)],emblem())
    def test_distinct_shape(self):
        occupied=[sum(ch not in (' ','\u2800') for ch in line) for line in emblem()]
        self.assertGreater(max(occupied[-6:]),min(occupied[12:17])+5)
        self.assertGreater(max(occupied[3:10]),min(occupied[12:17])+3)
        self.assertEqual(emblem(),emblem())
    def test_invalid_dimensions(self):
        for w,h in [(0,23),(24,0),(True,23),(24,2.5),(201,23)]:
            with self.assertRaises(ValueError): emblem(w,h)
