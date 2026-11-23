from importlib.resources import files
import unittest


class TestTypedMarker(unittest.TestCase):
    def test_package_ships_py_typed(self):
        """PEP 561: without the marker, type checkers treat the installed
        package as untyped."""
        assert files("govee_local_api").joinpath("py.typed").is_file()
