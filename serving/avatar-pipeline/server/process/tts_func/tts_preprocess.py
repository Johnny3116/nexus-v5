import re

def clean_llm_output(text: str) -> str:
    # 1. Replace hyphens with space
    text = text.replace('-', ' ')

    # 2. Remove text in parentheses (including parentheses)
    text = re.sub(r'\([^)]*\)', '', text)

    # 3. Replace fancy apostrophe (’) with regular apostrophe (')
    text = text.replace('\u2019', "'")

    # 4. Normalize whitespace: collapse multiple spaces into one and strip
    text = re.sub(r'\s+', ' ', text).strip()

    # 5. Lowercase all letters (maybe make this a bit more advanced.)
    text = text.lower()
    return text
