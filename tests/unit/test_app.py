"""Initial render of the Streamlit app with AppTest: no models, no network (no question is asked)."""

from streamlit.testing.v1 import AppTest

from agentguard.config import PROJECT_ROOT
from agentguard.ui import DEMO_QUESTIONS

APP = str(PROJECT_ROOT / "app" / "streamlit_app.py")


def render() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    return at


def test_intro_lists_the_ten_firms_and_the_problem() -> None:
    at = render()
    text = " ".join(m.value for m in at.markdown)
    assert "worse than useless" in text and "refuses when the filings don't say" in text
    firms = next(c.value for c in at.caption if c.value.startswith("**Firms in the corpus"))
    assert "Savvy Advisors" in firms and firms.count(",") == 9


def test_question_box_and_ask_button_share_one_form() -> None:
    at = render()
    assert [b.label for b in at.button] == ["Ask"]
    assert len(at.text_input) == 1
    options = next(s.options for s in at.selectbox if s.label == "Demo question")
    assert len(options) == len(DEMO_QUESTIONS)
    assert [o.split(" · ")[0] for o in options][4] == "Honest refusal"
