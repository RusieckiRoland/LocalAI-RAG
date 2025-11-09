# tests/test_constants.py
import constants

def test_constants_exist_and_nonempty():
    assert isinstance(constants.ANSWER_PREFIX, str) and constants.ANSWER_PREFIX
    assert isinstance(constants.FOLLOWUP_PREFIX, str) and constants.FOLLOWUP_PREFIX
    assert isinstance(constants.UML_CONSULTANT, str) and constants.UML_CONSULTANT