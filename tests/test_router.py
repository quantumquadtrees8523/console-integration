from custom_components.console import router
from custom_components.console.conversation import confirmed_reply


def test_plain_commands_are_told_from_everything_else():
    for text in ("turn off the desk lamp", "Play jazz in the kitchen", "please dim the bedroom to 30%", "set the thermostat to 68"):
        assert router.plain_command(text), text
    for text in (
        "add a dashboard for the kids' room",
        "why is the hallway light offline",
        "turn off the lights every night at 11",
        "what's on right now",
        "turn the porch light on when the sun sets",
    ):
        assert not router.plain_command(text), text


def test_a_label_is_taken_off_the_reply():
    assert router.split_label("The lamp is off. [[control]]") == ("The lamp is off.", "control")
    assert router.split_label("The lamp is off.") == ("The lamp is off.", None)
    assert router.split_label("Brackets [[like this]] stay.") == ("Brackets [[like this]] stay.", None)


def test_labels_from_tools_and_intents():
    assert router.category_for_tools([("act", {})]) == "control"
    assert router.category_for_tools([("house_map", {}), ("routine", {})]) == "customization"
    assert router.category_for_tools([("diagnose_device", {}), ("act", {})]) == "troubleshooting"
    assert router.category_for_tools([("get_skill", {"name": "welcome"})]) == "setup"
    assert router.category_for_tools([]) == "other"
    assert router.category_for_intent("HassTurnOff") == "control"
    assert router.category_for_intent("HassGetState") == "status"
    assert router.category_for_intent(None) == "other"


class _Result:
    def __init__(self, data, error=None):
        self.result = type("R", (), {"data": data, "error": error})()


class _Call:
    def __init__(self, name):
        self.tool_name = name


def test_a_confirmed_command_is_answered_from_the_read_back():
    checked = {"results": [{"id": "light.desk", "name": "Desk lamp", "result": "CHECKED", "now": "off"}]}
    assert confirmed_reply([_Call("act")], [_Result(checked)]) == "Done. Desk lamp is off."
    dim = {"results": [{"id": "light.desk", "name": "Desk lamp", "result": "CHECKED", "now": "on", "brightness_pct": 40}]}
    assert confirmed_reply([_Call("act")], [_Result(dim)]) == "Done. Desk lamp is on at 40%."


def test_anything_unconfirmed_goes_back_to_the_model():
    not_confirmed = {"results": [{"id": "light.desk", "name": "Desk lamp", "result": "NOT CONFIRMED", "now": "on"}]}
    assert confirmed_reply([_Call("act")], [_Result(not_confirmed)]) is None
    assert confirmed_reply([_Call("house_map")], [_Result({"rooms": []})]) is None
    assert confirmed_reply([_Call("act")], [_Result({"error": "no"}, error=True)]) is None
