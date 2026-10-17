"""Searchable, bounded terminal choices without a terminal UI dependency."""
from __future__ import annotations

import os
import shutil
import sys

from .terminal import _clip, safe_text


def choose(title, options, input_fn=None, output=None, current=None):
    """Return a listed ID or None; free text only filters the displayed choices."""
    output = output or sys.stdout
    options = [(ident, safe_text(label)) for ident, label in options]
    if not options:
        return None
    if input_fn is None and os.name == 'posix' and sys.stdin.isatty() and getattr(output, 'isatty', lambda: False)():
        return _terminal(title, options, output, current)
    ask = input_fn or input
    filtered = options
    while True:
        print(safe_text(title), file=output)
        for index, (ident, label) in enumerate(filtered, 1):
            print(f"  {index}. {label} [{safe_text(ident)}]" + (' · current' if ident == current else ''), file=output)
        answer = ask('Choice number or ID · /search · Enter cancels › ').strip()
        if not answer or answer.lower() in ('cancel', 'q', 'exit', 'back'):
            return None
        if answer.startswith('/'):
            query = answer[1:].casefold()
            filtered = [(ident, label) for ident, label in options if query in (str(ident) + ' ' + label).casefold()]
            if not filtered:
                print('No matches. Use / to show all choices.', file=output)
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(filtered):
            return filtered[int(answer) - 1][0]
        for ident, _ in filtered:
            if answer == str(ident):
                return ident
        raise ValueError('choose a listed number or ID, or /search')


def _terminal(title, options, output, current):
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    before = termios.tcgetattr(fd)
    selected = next((i for i, item in enumerate(options) if item[0] == current), 0)
    query = ''
    search_mode = False
    filtered = options
    drawn = 0
    page = 4

    def draw():
        nonlocal drawn, page
        try:
            size = os.get_terminal_size(output.fileno())
        except (OSError, AttributeError):
            size = shutil.get_terminal_size((80, 24))
        width = max(1, (size.columns or 80) - 1)
        page = max(1, (size.lines or 24) - 4)
        start = max(0, min(selected - page + 1, len(filtered) - page))
        rows = [safe_text(title), '↑↓ navigate · Enter/Space select · Esc/← back', 'Search: ' + query]
        for index in range(start, min(start + page, len(filtered))):
            ident, label = filtered[index]
            rows.append(('› ' if index == selected else '  ') + label + (' · current' if ident == current else ''))
        if not filtered:
            rows.append('No matches · Backspace to edit')
        if drawn:
            output.write(f'\x1b[{drawn}A\r\x1b[J')
        for row in rows:
            indent = len(row) - len(row.lstrip(' '))
            output.write(' ' * min(indent, width) + _clip(row.lstrip(' '), max(0, width - indent)) + '\n')
        drawn = len(rows)
        output.flush()

    def escape_key():
        # Read only one sequence, preserving rapidly queued arrows/Enter.
        if not select.select([fd], [], [], .08)[0]:
            return 'cancel'
        head = os.read(fd, 1)
        if head not in (b'[', b'O'):
            return 'cancel'
        sequence = b''
        for _ in range(12):
            if not select.select([fd], [], [], .08)[0]:
                break
            char = os.read(fd, 1)
            sequence += char
            if b'@' <= char <= b'~':
                break
        return {b'A': 'up', b'B': 'down', b'D': 'cancel', b'5~': 'pageup', b'6~': 'pagedown', b'H': 'home', b'F': 'end', b'1~': 'home', b'4~': 'end'}.get(sequence, 'ignore')

    try:
        # cbreak preserves normal output newline processing and avoids dropped input.
        tty.setcbreak(fd, when=termios.TCSANOW)
        draw()
        while True:
            key = os.read(fd, 1)
            if not key or key in (b'\x03', b'\x04'):
                return None
            action = escape_key() if key == b'\x1b' else None
            if action == 'cancel':
                return None
            if (key in (b'\r', b'\n') or (key == b' ' and not search_mode)) and filtered:
                return filtered[selected][0]
            if action in ('up', 'down', 'pageup', 'pagedown', 'home', 'end') and filtered:
                if action == 'home': selected = 0
                elif action == 'end': selected = len(filtered) - 1
                elif action == 'up': selected = max(0, selected - 1)
                elif action == 'down': selected = min(len(filtered) - 1, selected + 1)
                elif action == 'pageup': selected = max(0, selected - page)
                elif action == 'pagedown': selected = min(len(filtered) - 1, selected + page)
            elif key in (b'\x7f', b'\x08'):
                query = query[:-1]
                filtered = [(i, label) for i, label in options if query.casefold() in (str(i) + ' ' + label).casefold()]
                selected = 0
            elif action is None and key >= b' ' and key != b'\x7f':
                char = key.decode('utf-8', errors='ignore')
                if char == '/' and not query:
                    search_mode = True
                    continue
                if len(query) < 160:
                    query += ' ' if char == ' ' else safe_text(char)
                    filtered = [(i, label) for i, label in options if query.casefold() in (str(i) + ' ' + label).casefold()]
                    selected = 0
            draw()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, before)
        output.write('\n')
        output.flush()
