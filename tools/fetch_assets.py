"""Materialize immutable upstream LFS assets without git-lfs or cloud secrets.

Runtime downloads only assets reachable from the live catalog and web pages.
Use --scope all for historical art and firmware source assets. --check is offline.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def verified(path: Path, entry: dict) -> bool:
    if not path.is_file() or path.stat().st_size != entry['size']:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest() == entry['sha256']


def destination(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Asset path escapes the project')
    return path


def install_group(root: Path, upstream: dict, entries: list[dict]) -> int:
    missing = [entry for entry in entries if not verified(destination(root, entry['path']), entry)]
    if not missing:
        return 0
    entry = entries[0]
    available = next((destination(root, e['path']) for e in entries if e not in missing), None)
    cache = root / '.asset-cache'
    cache.mkdir(exist_ok=True)
    cached = cache / entry['sha256']
    if available is None and verified(cached, entry):
        available = cached
    if available is None:
        url = 'https://media.githubusercontent.com/media/' + upstream['repository'] + '/' + upstream['commit'] + '/' + quote(entry['path'], safe='/')
        for attempt in range(3):
            part = None
            try:
                request = Request(url, headers={'User-Agent': 'Lingxi-Asset-Installer/1.0'})
                with urlopen(request, timeout=90) as response, tempfile.NamedTemporaryFile(dir=cache, suffix='.part', delete=False) as output:
                    part = Path(output.name)
                    total = 0
                    while block := response.read(1024 * 1024):
                        total += len(block)
                        if total > entry['size']:
                            raise ValueError(f"Unexpected size: {entry['path']}")
                        output.write(block)
                if not verified(part, entry):
                    raise ValueError(f"SHA-256/size mismatch: {entry['path']}")
                part.replace(cached)
                available = cached
                break
            except Exception:
                if part is not None:
                    part.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
    for item in missing:
        target = destination(root, item['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        # Never expose partially written firmware or images to a live server.
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.part', delete=False) as output:
            staging = Path(output.name)
            with available.open('rb') as source:
                shutil.copyfileobj(source, output)
        staging.chmod(0o644)
        staging.replace(target)
    if cached.exists():
        cached.unlink()
    return len(missing)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('runtime', 'all'), default='runtime')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(argv)
    lock = json.loads((ROOT / 'assets.lock.json').read_text('utf-8'))
    entries = [e for e in lock['assets'] if args.scope == 'all' or e['runtime']]
    if args.check:
        missing = [e['path'] for e in entries if not verified(destination(ROOT, e['path']), e)]
        if missing:
            print('\n'.join(missing[:20]))
            print(f'{len(missing)} missing/invalid assets. Run python tools/fetch_assets.py --scope {args.scope}')
            return 1
        print(f'{len(entries)} assets verified (SHA-256 and size).')
        return 0
    groups = {}
    for entry in entries:
        groups.setdefault(entry['sha256'], []).append(entry)
    print(f"Preparing {len(entries)} assets, {sum(v[0]['size'] for v in groups.values()) / 1048576:.1f} MiB unique ({args.scope}).", flush=True)
    with ThreadPoolExecutor(max_workers=max(1, min(8, args.workers))) as executor:
        futures = {executor.submit(install_group, ROOT, lock['upstream'], group): group[0]['path'] for group in groups.values()}
        for i, future in enumerate(as_completed(futures), 1):
            try:
                future.result()
            except Exception as error:
                raise RuntimeError(f"Asset unavailable: {futures[future]} ({type(error).__name__})") from error
            if i % 20 == 0 or i == len(futures):
                print(f'{i}/{len(futures)} verified', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
