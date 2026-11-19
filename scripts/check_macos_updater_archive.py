"""Check raw tar members using the same one-app-root layout as the native updater."""
import sys
import tarfile
from pathlib import PurePosixPath


def check_archive(path, app_name):
    found = False
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            if any(part.startswith('._') for part in parts):
                raise ValueError('AppleDouble metadata is incompatible with the native macOS updater')
            # The native extractor strips the first component, including a leading './'.
            if not parts or member.name.split('/', 1)[0] != app_name or '..' in parts:
                raise ValueError('macOS updater archive must contain exactly one application root')
            found = True
    if not found:
        raise ValueError('Empty macOS updater archive')


if __name__ == '__main__':
    check_archive(sys.argv[1], sys.argv[2])
