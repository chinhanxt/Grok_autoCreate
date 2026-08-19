import re
from config import generate_random_name


def test_generate_random_name_formula():
    for _ in range(50):
        first_name, last_name = generate_random_name()
        # Pattern: User_<2-digits><2-uppercase-letters>
        match = re.match(r"^User_(\d{2})([A-Z]{2})$", first_name)
        assert match is not None, f"Generated name {first_name} does not match formula User_XXYY"
        assert len(last_name) == 2
        assert last_name == match.group(2)
