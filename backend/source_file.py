"""Locate imported JSON references without changing the source text or its line numbers."""
from __future__ import annotations

import json
import re
from bisect import bisect_right


def json_locations(text: str, pointers: set[str]) -> dict[str, dict[str, int]]:
    branches: dict = {}
    for pointer in pointers:
        if pointer and (not pointer.startswith('/') or re.search(r'~(?![01])', pointer)):
            continue
        branch = branches
        for part in pointer[1:].split('/') if pointer else []:
            branch = branch.setdefault(part.replace('~1', '/').replace('~0', '~'), {})
        branch[None] = pointer
    if not branches:
        return {}

    decoder = json.JSONDecoder()
    whitespace = re.compile(r'[ \t\r\n]*')
    spans: dict[str, tuple[int, int]] = {}

    def skip(position: int) -> int:
        return whitespace.match(text, position).end()

    def visit(position: int, branch: dict) -> int:
        start = skip(position)
        if not any(key is not None for key in branch):
            _, end = decoder.raw_decode(text, start)
        elif text[start] == '{':
            end = skip(start + 1)
            while text[end] != '}':
                name, end = decoder.raw_decode(text, end)
                end = skip(end)
                end = visit(end + 1, branch.get(name, {}))  # Skip the colon.
                end = skip(end)
                if text[end] != ',':
                    break
                end = skip(end + 1)
            end += 1
        elif text[start] == '[':
            end, index = skip(start + 1), 0
            while text[end] != ']':
                end = skip(visit(end, branch.get(str(index), {})))
                index += 1
                if text[end] != ',':
                    break
                end = skip(end + 1)
            end += 1
        else:
            _, end = decoder.raw_decode(text, start)
        if None in branch:
            spans[branch[None]] = (start, end)
        return end

    visit(0, branches)
    starts = [0, *(match.end() for match in re.finditer('\n', text))]

    def column(line: int, position: int) -> int:
        # Browser string offsets use UTF-16 code units, including astral characters.
        return len(text[starts[line - 1]:position].encode('utf-16-le')) // 2 + 1

    result = {}
    for pointer, (start, end) in spans.items():
        line = bisect_right(starts, start)
        end_line = bisect_right(starts, max(start, end - 1))
        result[pointer] = dict(line=line, endLine=end_line,
                               column=column(line, start), endColumn=column(end_line, end))
    return result
