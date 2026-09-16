"""Generate the committed wheel lock from pip's resolved artifact report."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from packaging.utils import parse_wheel_filename

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest().upper()

def main() -> int:
    p = argparse.ArgumentParser(); p.add_argument('--report', type=Path, required=True); p.add_argument('--wheels', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(); report = json.loads(a.report.read_text(encoding='utf-8'))
    items = []
    for row in report['install']:
        url = row['download_info']['url']; filename = Path(url.split('?', 1)[0]).name.replace('%2B', '+')
        candidates = list(a.wheels.glob(filename))
        if len(candidates) != 1: raise SystemExit(f'wheel missing or ambiguous: {filename}')
        wheel = candidates[0]; name, version, build, tags = parse_wheel_filename(wheel.name)
        expected = (row['download_info'].get('archive_info', {}).get('hashes') or {}).get('sha256')
        actual = sha256(wheel)
        if expected and expected.upper() != actual: raise SystemExit(f'hash mismatch: {wheel.name}')
        items.append({'name': str(name), 'version': str(version), 'filename': wheel.name, 'url': url, 'sha256': actual, 'tags': sorted(str(t) for t in tags)})
    items.sort(key=lambda x: (x['name'], x['version'], x['filename']))
    payload = {'schema': 1, 'target': {'python': '3.11.9', 'implementation': 'CPython', 'platform': 'win_amd64'}, 'artifacts': items}
    a.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(f'wrote {len(items)} artifacts to {a.output}')
    return 0
if __name__ == '__main__': raise SystemExit(main())
