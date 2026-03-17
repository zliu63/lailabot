def _hard_split(text: str, max_length: int) -> list[str]:
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


def split_message(text: str, max_length: int = 4096) -> list[str]:
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    paragraphs = text.split("\n\n")
    messages = []
    current = ""

    for para in paragraphs:
        if len(para) > max_length:
            if current:
                messages.append(current)
                current = ""
            messages.extend(_hard_split(para, max_length))
        elif not current:
            current = para
        elif len(current) + 2 + len(para) <= max_length:
            current += "\n\n" + para
        else:
            messages.append(current)
            current = para

    if current:
        messages.append(current)

    return messages
