import re

# Regex to match emojis and other symbol characters TTS shouldn't read
_EMOJI_RE = re.compile(
    "["
    "😀-🙏"  # emoticons
    "🌀-🗿"  # symbols & pictographs
    "🚀-🛿"  # transport & map
    "🇠-🇿"  # flags
    "✂-➰"  # dingbats
    "Ⓜ-🉑"  # misc
    "🤀-🧿"  # supplemental symbols
    "🨀-🩯"  # chess symbols
    "🩰-🫿"  # symbols extended-A
    "☀-⛿"  # misc symbols
    "︀-️"  # variation selectors
    "‍"             # zero width joiner
    "⭐-⭕"  # stars
    "]+",
    flags=re.UNICODE,
)

# Common markdown/formatting that slips through
_MARKDOWN_RE = re.compile(r"[*_~`#>|]")


def clean_llm_output(text: str) -> str:
    # 1. Strip emojis
    text = _EMOJI_RE.sub("", text)

    # 2. Strip markdown formatting chars
    text = _MARKDOWN_RE.sub("", text)

    # 3. Replace hyphens with space
    text = text.replace("-", " ")

    # 4. Remove text in parentheses (including parentheses)
    text = re.sub(r'\([^)]*\)', "", text)

    # 5. Replace fancy apostrophe with regular apostrophe
    text = text.replace("’", "'")

    # 6. Normalize whitespace
    text = re.sub(r'\s+', " ", text).strip()

    # 7. Lowercase
    text = text.lower()
    return text
