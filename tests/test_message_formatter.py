from lailabot.message_formatter import split_message


def test_empty_string_returns_empty_list():
    assert split_message("") == []


def test_short_text_returns_single_item():
    assert split_message("hello world") == ["hello world"]


def test_splits_on_paragraph_boundaries():
    text = "paragraph one\n\nparagraph two\n\nparagraph three"
    # Use small max_length to force each paragraph into its own message
    result = split_message(text, max_length=15)
    assert result == ["paragraph one", "paragraph two", "paragraph three"]


def test_accumulates_paragraphs_within_limit():
    text = "aaa\n\nbbb\n\nccc\n\nddd"
    # max_length=9 fits "aaa\n\nbbb" (7 chars) but not adding "\n\nccc" (12)
    result = split_message(text, max_length=9)
    assert result == ["aaa\n\nbbb", "ccc\n\nddd"]


def test_hard_splits_oversized_paragraph():
    text = "a" * 10
    result = split_message(text, max_length=4)
    assert result == ["aaaa", "aaaa", "aa"]


def test_mixed_normal_and_oversized_paragraphs():
    text = "hi\n\n" + "x" * 8 + "\n\nbye"
    result = split_message(text, max_length=5)
    assert result == ["hi", "xxxxx", "xxx", "bye"]
