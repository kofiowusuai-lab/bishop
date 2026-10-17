"""Terminal-native Bishop identity. Rendering never executes terminal input."""
from __future__ import annotations

import os
from functools import lru_cache
import re
import shutil
import sys
import unicodedata

# Solid five-row lettering: a continuous left stem keeps B distinct from 8.
_WORDMARK = (
    '████▄  ███  ▄████  ██ ██  ▄███▄  ████▄',
    '██ ██   █   ██     ██ ██  ██ ██  ██ ██',
    '████▄   █   ▀███▄  █████  ██ ██  ████▀',
    '██ ██   █      ██  ██ ██  ██ ██  ██',
    '████▀  ███  ████▀  ██ ██  ▀███▀  ██',
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



@lru_cache(maxsize=32)
def _indexed_color(r, g, b):
    levels = (0, 95, 135, 175, 215, 255)
    coords = [min(range(6), key=lambda i: abs(levels[i] - value)) for value in (r, g, b)]
    cube = 16 + coords[0] * 36 + coords[1] * 6 + coords[2]
    cube_error = sum((levels[i] - value) ** 2 for i, value in zip(coords, (r, g, b)))
    grey = min(range(24), key=lambda i: sum((8 + i * 10 - value) ** 2 for value in (r, g, b)))
    grey_error = sum((8 + grey * 10 - value) ** 2 for value in (r, g, b))
    return 232 + grey if grey_error < cube_error else cube


def render_boot(info: dict, width=None, color=None) -> str:
    """Compose a compact identity and truthful startup information."""
    from .identity import emblem
    from . import __version__
    width = max(1, int(width if width is not None else shutil.get_terminal_size((80, 24)).columns))
    width = min(width, 108)
    use_color = bool(sys.stdout.isatty() if color is None else color) and 'NO_COLOR' not in os.environ
    truecolor = os.environ.get('COLORTERM', '').lower() in ('truecolor', '24bit') or '-direct' in os.environ.get('TERM', '')
    palette = {'ivory': (231, 224, 209), 'gold': (218, 184, 121),
               'bronze': (182, 138, 77), 'muted': (133, 128, 118)}
    def paint(text, tone='ivory'):
        if not use_color or not text: return text
        r, g, b = palette[tone]
        prefix = f'\x1b[38;2;{r};{g};{b}m' if truecolor else f'\x1b[38;5;{_indexed_color(r,g,b)}m'
        return prefix + text + '\x1b[0m'
    def value(key, default):
        return safe_text(info.get(key, default))
    margin = 2 if width >= 48 else 0
    content_width = max(1, width - margin * 2)
    wide = width >= 72
    columns = width >= 48
    art_width, art_height = (24, 23) if wide else (17, 19)
    gap = 4 if wide else 3
    details_width = content_width - art_width - gap if columns else content_width
    def row(text='', tone='ivory'):
        return paint(_clip(text, details_width), tone)
    version = value('version', __version__)
    details = [row('BISHOP  /  '+version, 'gold'), '']
    if wide:
        details.extend(paint(line, 'gold' if i < 3 else 'bronze') for i, line in enumerate(_WORDMARK))
        details.append('')
    def field(label, text, tone='ivory'):
        label_width = min(9, max(1, details_width // 3))
        label_text = _clip(label, label_width - 1)
        return paint(label_text.ljust(label_width), 'muted') + paint(_clip(text, details_width - label_width), tone)
    details.extend([row('Independent agent runtime', 'muted'), '',
                    field('Model', value('model', 'Choose a provider to begin'), 'gold'),
                    field('Provider', value('provider', 'Not configured')),
                    field('Profile', value('profile', 'Not configured')),
                    field('Session', value('session', 'local'), 'muted'),
                    field('Home', value('home', '~/.bishop'), 'muted'), ''])
    def inventory(key, label):
        items = info.get(key, [])
        count = len(items) if isinstance(items, (list, tuple, set, dict)) else items
        result = [row(f'{label} ({count})', 'bronze')]
        if not isinstance(items, (list, tuple, set, dict)) or not items:
            return result
        names = sorted(items, key=str) if isinstance(items, set) else list(items)
        shown = [safe_text(name) for name in names[:40]]
        if len(names) > 40: shown.append(f'+{len(names)-40} more')
        line = ''
        for name in shown:
            name = _clip(name, details_width)
            candidate = line + ' · ' + name if line else name
            if _cells(candidate) > details_width:
                if line: result.append(row(line, 'muted'))
                line = name
            else: line = candidate
        if line: result.append(row(line, 'muted'))
        return result
    details.extend(inventory('tools', 'Available tools'))
    details.append('')
    details.extend(inventory('skills', 'Installed skills'))
    lines = ['']
    if columns:
        art = emblem(width=art_width, height=art_height, color=use_color)
        if use_color and not truecolor:
            art = [re.sub(r'\x1b\[38;2;(\d+);(\d+);(\d+)m',
                          lambda match: f'\x1b[38;5;{_indexed_color(*map(int,match.groups()))}m', line) for line in art]
        for i in range(max(len(art), len(details))):
            left = art[i] if i < len(art) else ' ' * art_width
            right = details[i] if i < len(details) else ''
            lines.append(' ' * margin + left + ' ' * gap + right)
    else:
        lines.extend(details)
    lines.extend([' ' * margin + paint('─' * min(content_width, 76), 'muted'),
                  ' ' * margin + paint(_clip('/help commands  ·  /model models  ·  /setup providers', content_width), 'muted'), ''])
    return '\n'.join(lines) + '\n'


def print_boot(info, stream=None):
    """Use color only when the destination is a terminal."""
    stream = sys.stdout if stream is None else stream
    stream.write(render_boot(info, color=bool(getattr(stream, 'isatty', lambda: False)())))
