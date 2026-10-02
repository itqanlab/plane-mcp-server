"""Plain text from rich text, as an agent reads a ticket."""

from plane_mcp.toolkit.text import plain_text, truncate


def test_tags_are_stripped_and_entities_unescaped():
    assert plain_text("<p>Fix <code>a &amp; b</code> &quot;now&quot;</p>") == 'Fix a & b "now"'


def test_escaped_markup_stays_text_not_tags():
    assert plain_text("<p>keep &lt;code&gt; literal</p>") == "keep <code> literal"


def test_block_elements_become_line_breaks():
    html = "<div><h2>0. Investigate</h2>\n<ol><li>one</li><li>two</li></ol><p>para<br/>next</p></div>"
    assert plain_text(html) == "0. Investigate\none\ntwo\npara\nnext"


def test_inline_tags_become_spaces_and_runs_collapse():
    assert plain_text("a<b>b</b>c   \t d&nbsp;e") == "a b c d e"


def test_empty_and_none():
    assert plain_text(None) == "" and plain_text("") == ""


def test_truncation_flags_only_a_real_cut():
    assert truncate("abcdef", 3) == ("abc", True)
    assert truncate("abc", 3) == ("abc", False)
    assert truncate("abcdef", 0) == ("abcdef", False)
