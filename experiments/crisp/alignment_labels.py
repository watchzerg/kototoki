"""Whether frozen Crisp v0.8.41 tokenise_words() has an alignment label.

This is the native predicate, not Unicode lexical-content detection. The native
filter retains apostrophe and many symbols/punctuation outside its listed blocks,
but removes fullwidth Latin/digits within FF00..FF65. Do not broaden the filter.
"""

UPSTREAM_SOURCE_REVISION = '340d7085eaa53c40a46dcb73a6d3d0448a480006'
UPSTREAM_SOURCE_URL = 'https://github.com/CrispStrobe/CrispASR/blob/340d7085eaa53c40a46dcb73a6d3d0448a480006/src/crispasr_aligner.cpp'
UPSTREAM_SOURCE_SHA256 = 'e5bebecbdef4d74c59a25cb0cb4ef09fbb00e9cf712db8a408f7b952ff973269'
UPSTREAM_SOURCE_LINES = {'punctuation_predicate': '91-101', 'tokenise_words': '127-159', 'qwen_empty_labels': '298-304'}


def is_alignment_punctuation(codepoint: int) -> bool:
    """Port the native C-locale ASCII and explicit Unicode block predicate."""
    if codepoint == 0x27:  # Apostrophe is explicitly retained by upstream.
        return False
    if codepoint < 0x80:
        alphanumeric = (0x30 <= codepoint <= 0x39 or 0x41 <= codepoint <= 0x5A or 0x61 <= codepoint <= 0x7A)
        ascii_whitespace = codepoint in (0x20, 0x09, 0x0A, 0x0D, 0x0B, 0x0C)
        return not alphanumeric and not ascii_whitespace
    return any(first <= codepoint <= last for first, last in (
        (0x2000, 0x206F), (0x3000, 0x303F), (0xFE10, 0xFE1F), (0xFE30, 0xFE4F), (0xFF00, 0xFF65)))


def has_alignment_labels(text: str) -> bool:
    """Exactly test nonempty native labels for valid original UTF-8 text.

    tokenise_words only separates space, tab, LF and CR. Its other ASCII
    whitespace and non-ASCII whitespace can remain labels; str.strip() or a
    Unicode-category test is therefore not equivalent to this contract.
    """
    return any(ord(char) not in (0x20, 0x09, 0x0A, 0x0D) and not is_alignment_punctuation(ord(char)) for char in text)
