"""Terminal-native Bishop identity. Rendering never executes terminal input."""
from __future__ import annotations

import os
import re
import shutil
import sys
import unicodedata

# Original chess bishop silhouette: mitre, diagonal cut, collar and broad base.
_EMBLEM = (
    '         ●         ',
    '        ●●●        ',
    '       ●●●●●       ',
    '      ●●●● ●●      ',
    '     ●●●● ●●●●     ',
    '     ●●● ●●●●●     ',
    '      ● ●●●●●      ',
    '       ●●●●●       ',
    '        ●●●        ',
    '      ●●●●●●●      ',
    '        ●●●        ',
    '       ●●●●●       ',
    '      ●●●●●●●      ',
    '    ●●●●●●●●●●●    ',
    '   ●●●●●●●●●●●●●   ',
)
_BANNER = (
    '████▄  ██  ▄████  ██  ██  ▄████▄  ████▄ ',
    '██  ██ ██  ██     ██  ██  ██  ██  ██  ██',
    '████▄  ██  ▀███▄  ██████  ██  ██  ████▀ ',
    '██  ██ ██     ██  ██  ██  ██  ██  ██    ',
    '████▀  ██  ████▀  ██  ██  ▀████▀  ██    ',
)
# Consume complete OSC/DCS sequences before generic escapes, including ST.
_ESCAPE = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[P^_].*?\x1b\\|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]', re.DOTALL)


def safe_text(text) -> str:
    """Remove terminal escapes, control characters and invisible format controls."""
    text = _ESCAPE.sub('', str(text))
    cleaned = []
    for char in text:
        category = unicodedata.category(char)
        if char in '\r\n\t':
            cleaned.append(' ')
        elif category not in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp'):
            cleaned.append(char)
    return ' '.join(''.join(cleaned).split())


def _cells(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in text)


def _clip(text, width):
    if width <= 0:
        return ''
    text = safe_text(text)
    if _cells(text) <= width:
        return text
    if width == 1:
        return '…'
    result = ''
    for char in text:
        if _cells(result + char) > width - 1:
            break
        result += char
    return result + '…'


def render_boot(info: dict, width=None, color=None) -> str:
    """Return a responsive startup panel.

    Metadata keys: version, profile, provider, model, tools, skills, home,
    session. All values are untrusted display text. ``NO_COLOR`` always wins.
    """
    width = max(1, int(width if width is not None else shutil.get_terminal_size((80, 24)).columns))
    use_color = bool(sys.stdout.isatty() if color is None else color) and 'NO_COLOR' not in os.environ
    gold = '\x1b[38;5;220m' if use_color else ''
    amber = '\x1b[38;5;179m' if use_color else ''
    dim = '\x1b[38;5;245m' if use_color else ''
    reset = '\x1b[0m' if use_color else ''

    def paint(text, tone=gold):
        return tone + text + reset if text else ''

    def value(key, default='not configured'):
        item = info.get(key, default)
        if isinstance(item, (list, tuple, set, dict)):
            item = len(item)
        return safe_text(item)

    title = 'BISHOP  ·  independent agent runtime'
    lines = []
    if width >= 46:
        lines.extend(paint(line.rstrip()) for line in _BANNER)
        lines.append(paint(_clip(title, width), amber))
    else:
        lines.append(paint(_clip(title, width)))
    lines.append('')
    detail_width = width - 26 if width >= 60 else width

    def inventory(key, title):
        items = info.get(key, 0)
        rows = [title + ' (' + value(key, 0) + ')']
        if not isinstance(items, (list, tuple, set, dict)) or not items:
            return rows
        names = list(items)
        if isinstance(items, set):
            names.sort(key=str)
        # Bound startup rendering even for unusually large skill inventories.
        shown = [safe_text(name) for name in names[:40]]
        if len(names) > 40:
            shown.append('+' + str(len(names) - 40) + ' more')
        line = ''
        for name in shown:
            name = _clip(name, detail_width)
            candidate = line + ', ' + name if line else name
            if _cells(candidate) > detail_width:
                rows.append(line)
                line = name
            else:
                line = candidate
        if line:
            rows.append(line)
        return rows

    details = [
        'Runtime  ' + value('version', '0.1.0'),
        '',
        'Profile  ' + value('profile', 'default'),
        'Provider ' + value('provider'),
        'Model    ' + value('model'),
        '',
        *inventory('tools', 'Available tools'),
        '',
        *inventory('skills', 'Installed skills'),
        '',
        'Home     ' + value('home', '~/.bishop'),
        'Session  ' + value('session', 'new'),
        '',
        'Type /help for commands',
    ]
    # Two-column panel retains the entire chess silhouette at common widths.
    if width >= 60:
        inside = width - 4
        lines.append(paint('┌' + '─' * (width - 2) + '┐', amber))
        for row in range(max(len(_EMBLEM), len(details))):
            emblem = _EMBLEM[row] if row < len(_EMBLEM) else ' ' * 19
            detail = _clip(details[row] if row < len(details) else '', inside - 22)
            padding = ' ' * max(0, inside - 22 - _cells(detail))
            lines.append(paint('│ ', amber) + paint(emblem) + '   ' + detail + padding + paint(' │', amber))
        lines.append(paint('└' + '─' * (width - 2) + '┘', amber))
    else:
        # Compact terminals prioritize actionable configuration over ornament.
        if width >= 24:
            lines.extend(paint(row) for row in _EMBLEM)
            lines.append('')
        lines.extend(_clip(row, width) for row in details if row)
    lines.append(paint(_clip('Your workspace. Your models. Your Bishop.', width), dim))
    return '\n'.join(lines) + '\n'


def print_boot(info, stream=None):
    """Print a panel with color only when the destination is a terminal."""
    stream = sys.stdout if stream is None else stream
    stream.write(render_boot(info, color=bool(getattr(stream, 'isatty', lambda: False)())))
