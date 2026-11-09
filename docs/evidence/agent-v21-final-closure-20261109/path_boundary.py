"""Pure path spelling normalization, not a filesystem permission override."""
import os
from pathlib import Path


def comparable(path):
    value = str(path)
    if value.startswith('\\\\?\\UNC\\'):
        value = '\\\\' + value[8:]
    elif value.startswith('\\\\?\\') and len(value) > 6 and value[4].isalpha() and value[5:7] == ':\\':
        value = value[4:]
    return Path(os.path.normcase(os.path.normpath(value)))


def within(resolved, root):
    # Caller resolves symlinks/reparse points first. Compare the same DOS/UNC
    # identity even if Windows returns its extended spelling during a rename.
    return comparable(resolved).is_relative_to(comparable(root))
