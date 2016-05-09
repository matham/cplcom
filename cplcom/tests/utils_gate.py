
import unittest


class UtilsTestCase(unittest.TestCase):

    def test_pretty_time(self):
        from cplcom.utils import pretty_time
        self.assertEquals(pretty_time(36574), '10:9:34.0')
