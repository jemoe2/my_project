import unittest

from src.utils.helpers import add_numbers


class TestHelpers(unittest.TestCase):
    def test_add_numbers(self):
        self.assertEqual(add_numbers(2, 3), 5)
        self.assertEqual(add_numbers(-1, 1), 0)


if __name__ == "__main__":
    unittest.main()
