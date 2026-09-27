#!/usr/bin/env python3
"""Keep a durable copy of the companion plugin sources inside this repository.

The plugins are pinned submodules, which makes them easy to follow but leaves
them entirely dependent on four repositories this project does not control and
cannot push to. If any of them disappears, its commits disappear with it: a
submodule pointer to a commit nobody hosts is not a backup, it is a broken link.

This tool copies the tracked files of each plugin at the pinned commit into
snapshots/plugins/<id>/, which is ordinary content in this repository and
therefore survives in its history. The submodules stay the working mechanism -
they are what builds, what the contract gate checks, and what `update` moves -
and the snapshot is the fallback for the day a remote is gone.

Commands
--------
    snapshot   refresh snapshots/ from the currently pinned submodules
    verify     check the snapshots match the pinned commits (the CI gate)
    update     report what upstream changed, and optionally re-pin
    restore    rebuild plugins/<id>/ from a snapshot, for when a remote is gone

verify is the important one. A backup nobody checks is a backup that has already
rotted, so it runs in CI next to the contract gate: if a plugin is re-pinned and
the snapshot is not refreshed in the same commit, the gate fails.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_REL = 'Code/plugins/plugins.json'
SNAPSHOT_DIR = 'snapshots/plugins'
UPSTREAM_FILE = 'UPSTREAM.json'


def run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(args, cwd=str(cwd or ROOT), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout


def plugins() -> list[dict]:
    """Every submodule this project backs up: the staged plugins and the
    prerequisites they need.

    A prerequisite is pinned here for the same reason a plugin is - the
    upstream repository can disappear, and a pointer to a commit nobody
    hosts is not a backup.
    """
    manifest = json.loads((ROOT / MANIFEST_REL).read_text(encoding='utf-8'))
    return manifest['plugins'] + manifest.get('prerequisites', [])


def pinned_sha(plugin_id: str) -> str | None:
    """The commit this repository records for the submodule, index first."""
    rel = f'plugins/{plugin_id}'
    out = run(['git', 'ls-files', '-s', '--', rel], check=False).strip()
    if out:
        return out.split()[1]
    out = run(['git', 'ls-tree', 'HEAD', '--', rel], check=False).strip()
    if out:
        return out.split()[2]
    return None


def submodule_files(plugin_id: str) -> list[str]:
    return [line for line in run(['git', '-C', f'plugins/{plugin_id}', 'ls-files']).splitlines() if line]


def is_checked_out(plugin: dict) -> bool:
    """Whether the submodule has content, without assuming its layout.

    A gitlink submodule materialises .git as a file, a hand-cloned one as a
    directory, and the project inside is not always at the root, so neither
    '.git exists' nor 'CMakeLists.txt exists' is the right test on its own.
    """
    submodule = ROOT / plugin['submodule']
    if not submodule.is_dir():
        return False
    return (submodule / '.git').exists() or any(submodule.iterdir())


def snapshot_scope(plugin: dict) -> list[str] | None:
    """The paths an entry backs up, or None for the whole tree.

    OStimNG is 256 MB of animation and texture assets that this project does not
    build, patch or ship - it only needs the code, so backing up its assets
    would put a quarter of a gigabyte into this repository's history to protect
    files nothing here can regenerate or consume. The scope is declared in the
    manifest rather than inferred from a size threshold, because "which files
    matter" is a judgement about this project, not a number.
    """
    scope = plugin.get('snapshotScope')
    return scope if scope else None


def in_scope(plugin: dict, rel: str) -> bool:
    scope = snapshot_scope(plugin)
    if scope is None:
        return True
    return any(rel == prefix or rel.startswith(prefix.rstrip('/') + '/') for prefix in scope)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(data: bytes) -> bytes:
    """Content with line endings forced to LF.

    The same commit checks out as CRLF or LF depending on the machine's git
    settings, so a byte comparison would report drift that is not drift.
    """
    return data.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def pinned_blob(plugin_id: str, rel: str) -> bytes | None:
    """A file's content at the commit this repository pins, not in the working tree.

    The working tree is not the pinned commit: plugin_patches.py applies this
    repository's own fixes to it before a build, and those fixes are repository
    content rather than drift. Reading the pin through git keeps this gate
    measuring what it exists to measure - that the durable copy still matches the
    commit being built - and stops it from failing on every patched build.
    """
    sha = pinned_sha(plugin_id)
    if not sha:
        return None
    result = subprocess.run(
        ['git', '-C', str(ROOT / 'plugins' / plugin_id), 'show', f'{sha}:{rel}'],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def snapshot_one(plugin: dict) -> dict:
    plugin_id = plugin['id']
    submodule = ROOT / plugin['submodule']
    if not is_checked_out(plugin):
        raise SystemExit(f"{plugin['submodule']} is not checked out; run git submodule update --init")

    target = ROOT / SNAPSHOT_DIR / plugin_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    digest = hashlib.sha256()
    copied = 0
    for rel in sorted(r for r in submodule_files(plugin_id) if in_scope(plugin, r)):
        source = submodule / rel
        if not source.is_file():
            continue
        # Written from the pinned commit, not from the working tree. The working
        # tree can carry this repository's own patches, and a backup that stored
        # patched content while recording the pin's hash would fail the very gate
        # that exists to check it - which is exactly what happened before this
        # was corrected.
        content = pinned_blob(plugin_id, rel)
        if content is None:
            content = source.read_bytes()
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        digest.update(rel.encode('utf-8'))
        digest.update(b'\0')
        digest.update(normalized(content))
        digest.update(b'\0')
        copied += 1

    url = run(['git', 'config', '--get', f'submodule.plugins/{plugin_id}.url'], check=False).strip()
    record = {
        'id': plugin_id,
        'upstream': url,
        'commit': pinned_sha(plugin_id),
        'files': copied,
        'contentSha256': digest.hexdigest(),
        'why': 'Durability copy of the pinned commit. Not a build input: the submodule builds. Kept so the code survives the upstream repository disappearing.',
    }
    (target / UPSTREAM_FILE).write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


def cmd_snapshot(_args) -> int:
    for plugin in plugins():
        record = snapshot_one(plugin)
        print(f"  {record['id']:<24} {record['files']:>4} files  {record['commit'][:8] if record['commit'] else '?'}  {record['contentSha256'][:12]}")
    print()
    print('snapshot refreshed; commit snapshots/ together with any submodule re-pin')
    return 0


def cmd_verify(_args) -> int:
    failures: list[str] = []
    checked = 0

    for plugin in plugins():
        plugin_id = plugin['id']
        target = ROOT / SNAPSHOT_DIR / plugin_id
        record_path = target / UPSTREAM_FILE

        if not record_path.is_file():
            failures.append(f"{plugin_id}: no snapshot; run 'snapshot' (the submodule alone is not a backup)")
            continue

        record = json.loads(record_path.read_text(encoding='utf-8'))
        current = pinned_sha(plugin_id)

        if record.get('commit') != current:
            failures.append(
                f"{plugin_id}: snapshot is of {str(record.get('commit'))[:8]} but the pinned commit is "
                f"{str(current)[:8]}; re-pin and refresh the snapshot in the same commit"
            )
            continue

        submodule = ROOT / plugin['submodule']
        if not is_checked_out(plugin):
            failures.append(f"{plugin_id}: submodule not checked out, cannot confirm the snapshot is current")
            continue

        digest = hashlib.sha256()
        missing: list[str] = []
        differing: list[str] = []
        for rel in sorted(r for r in submodule_files(plugin_id) if in_scope(plugin, r)):
            source = submodule / rel
            copy = target / rel
            if not source.is_file():
                continue
            if not copy.is_file():
                missing.append(rel)
                continue
            pinned = pinned_blob(plugin_id, rel)
            if pinned is None:
                failures.append(f"{plugin_id}: cannot read {rel} at the pinned commit")
                continue
            if normalized(pinned) != normalized(copy.read_bytes()):
                differing.append(rel)
            digest.update(rel.encode('utf-8'))
            digest.update(b'\0')
            digest.update(normalized(pinned))
            digest.update(b'\0')

        if missing:
            failures.append(f"{plugin_id}: snapshot is missing {len(missing)} file(s), e.g. {missing[0]}")
        if differing:
            failures.append(f"{plugin_id}: snapshot differs in {len(differing)} file(s), e.g. {differing[0]}")
        if not missing and not differing and digest.hexdigest() != record.get('contentSha256'):
            failures.append(f"{plugin_id}: snapshot content hash disagrees with its own record")
        if not missing and not differing:
            checked += 1

    if failures:
        print(f'SNAPSHOT CHECK FAILED ({len(failures)})')
        for failure in failures:
            print(f'  - {failure}')
        return 1

    print('SNAPSHOT OK')
    print(f'  {checked} plugin(s) have a durable copy matching the pinned commit')
    return 0


def cmd_update(args) -> int:
    """Report what upstream changed since the pinned commit."""
    for plugin in plugins():
        plugin_id = plugin['id']
        submodule = ROOT / 'plugins' / plugin_id
        if not (submodule / 'CMakeLists.txt').exists():
            print(f'  {plugin_id}: not checked out, skipped')
            continue

        fetch = run(['git', '-C', str(submodule), 'fetch', '--quiet', 'origin'], check=False)
        _ = fetch
        branch = run(['git', '-C', str(submodule), 'rev-parse', '--abbrev-ref', 'HEAD']).strip()
        upstream = run(['git', '-C', str(submodule), 'rev-parse', f'origin/{branch}'], check=False).strip()
        current = run(['git', '-C', str(submodule), 'rev-parse', 'HEAD']).strip()

        if not upstream:
            print(f'  {plugin_id}: no origin/{branch} to compare against')
            continue
        if upstream == current:
            print(f'  {plugin_id}: up to date at {current[:8]}')
            continue

        log = run(['git', '-C', str(submodule), 'log', '--oneline', f'{current}..{upstream}'], check=False)
        count = len([line for line in log.splitlines() if line.strip()])
        print(f'  {plugin_id}: {count} new commit(s) available ({current[:8]} -> {upstream[:8]})')
        for line in log.splitlines()[:8]:
            print(f'      {line.strip()}')
        if count > 8:
            print(f'      ... and {count - 8} more')

        if args.apply:
            run(['git', '-C', str(submodule), 'checkout', '--quiet', upstream])
            run(['git', 'add', f'plugins/{plugin_id}'])
            print(f'      re-pinned to {upstream[:8]}; now run snapshot and commit both together')

    return 0


def cmd_restore(args) -> int:
    """Rebuild plugins/<id>/ from the snapshot, for when a remote is gone."""
    plugin_id = args.plugin
    target = ROOT / SNAPSHOT_DIR / plugin_id
    if not target.is_dir():
        raise SystemExit(f'no snapshot for {plugin_id}')

    destination = ROOT / 'plugins' / plugin_id
    print(f'restoring plugins/{plugin_id} from snapshots/{plugin_id}')
    print('note: this materialises the source as plain files. The submodule entry in')
    print('.gitmodules still points at the upstream URL; remove it if the upstream is')
    print('permanently gone, otherwise a later submodule update would overwrite this.')

    if destination.exists():
        existing = [p for p in destination.rglob('*') if p.is_file()]
        if existing and not args.force:
            raise SystemExit(f'plugins/{plugin_id} is not empty ({len(existing)} files); pass --force to overwrite')

    copied = 0
    for source in sorted(target.rglob('*')):
        if not source.is_file() or source.name == UPSTREAM_FILE:
            continue
        rel = source.relative_to(target)
        out = destination / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, out)
        copied += 1

    print(f'restored {copied} file(s) into plugins/{plugin_id}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot')
    sub.add_parser('verify')
    update = sub.add_parser('update')
    update.add_argument('--apply', action='store_true', help='re-pin each submodule to its upstream tip')
    restore = sub.add_parser('restore')
    restore.add_argument('--plugin', required=True)
    restore.add_argument('--force', action='store_true')
    args = parser.parse_args()

    return {
        'snapshot': cmd_snapshot,
        'verify': cmd_verify,
        'update': cmd_update,
        'restore': cmd_restore,
    }[args.command](args)


if __name__ == '__main__':
    sys.exit(main())