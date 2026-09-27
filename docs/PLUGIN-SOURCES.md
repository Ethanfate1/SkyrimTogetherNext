# Companion plugin sources: durability and updating

The seven plugin repositories live in `plugins/` as git submodules pointing at
repositories this project does not own and cannot push to. That arrangement is
good for following upstream and bad for survival: a submodule records a commit
hash, and if the repository hosting that commit disappears, the hash points at
nothing. A submodule is not a backup.

OStim Standalone (`plugins/OStimNG`) is an eighth submodule of the same kind,
held for a different reason: it is the runtime OStim Together drives, so it is a
**prerequisite** rather than a companion. It is pinned so the project can state
which OStim build it supports, patch that build, and check its engine ids
against every address library this framework ships. It is not staged into the
archive - a player installs OStim themselves, and its own data tree is 256 MB of
animations and textures this project neither builds nor ships.

`snapshots/plugins/<id>/` is the backup. It holds the tracked files of each
plugin at the pinned commit as ordinary content of this repository, so they
survive in its history.

| | Submodule (`plugins/`) | Snapshot (`snapshots/`) |
| --- | --- | --- |
| What it is | a pointer to a commit in someone else's repository | plain files committed here |
| What builds | yes | no |
| Survives upstream deletion | no | yes |
| What the gates check | the consumer contract | that it matches the pinned commit |

An entry may declare `snapshotScope` to back up only part of its tree.
OStimNG does: its `data/` is 256 MB of assets nothing here builds, patches or
ships, so only its code is kept. The scope is declared in the manifest rather
than inferred from a size threshold, because which files matter is a judgement
about this project, not a number.

## Updating a plugin

```text
# 1. see what upstream has that this project does not
python Code/plugins/tools/plugin_snapshot.py update

# 2. re-pin the submodules to their upstream tips
python Code/plugins/tools/plugin_snapshot.py update --apply

# 3. refresh the snapshots and run the gates
python Code/plugins/tools/plugin_snapshot.py snapshot
python Code/plugins/tools/strpm_contract.py check
python Code/plugins/tools/plugin_snapshot.py verify

# 4. commit the submodule pointer and the snapshot together
```

Step 4 is the one that matters. The snapshot gate fails when a plugin is
re-pinned and `snapshots/` was not refreshed in the same commit, which is what
stops a backup from silently falling behind the thing it backs up.

`update` only reports by default. `--apply` moves the working tree and stages
the new pointer; it never commits, because re-pinning a plugin is a decision
that should be reviewed alongside what the plugin changed.

## If an upstream repository disappears

```text
python Code/plugins/tools/plugin_snapshot.py restore --plugin OStimTogether
```

This materialises the plugin's source from the snapshot. It refuses to write
into a populated directory without `--force`, so it cannot quietly overwrite a
working tree.

Two things to do afterwards, because restoring is only half the job:

1. **Decide what to do with the submodule entry.** `.gitmodules` still points
   at the dead URL, and a later `git submodule update` would replace the
   restored files with a fetch failure or, worse, with whatever now answers at
   that URL. Either remove the entry and keep the source as ordinary
   directories, or point it at wherever the project moved to.
2. **Record the fork point.** The snapshot is of one commit, not of the
   project's future. Anyone continuing the work is starting from that commit.

## Fixing a bug in plugin source

The submodules cannot be pushed to (see above), and CI checks them out with
`--force`, which discards every local change before anything is built. Editing
`plugins/<id>/src/` therefore produces a fix that never reaches a package.

Fixes live in `Code/plugins/patches/<plugin>/` instead, as ordinary content of
this repository, and `Code/plugins/tools/plugin_patches.py` applies them to the
submodule working tree immediately before the plugin is configured and built.

```text
python Code/plugins/tools/plugin_patches.py apply     # CI: before the plugin build
python Code/plugins/tools/plugin_patches.py verify    # CI gate: patches still apply
python Code/plugins/tools/plugin_patches.py check     # local: are they applied?
python Code/plugins/tools/plugin_patches.py revert    # local: back to the pin
```

`apply` is idempotent, so a re-run is a no-op rather than a failure. `verify`
checks each patch against the **index** (`git apply --check --cached`), which
holds the pinned content even when the patch is already applied to the working
tree - so a patch that has stopped matching the pin is caught rather than
masked.

The rule to remember when re-pinning a plugin: **if a patch stops applying, the
pin moved and the patch has to be rewritten in the same commit.** `verify` fails
until it is. `plugin_snapshot.py` reads the pin through git for the same reason,
so an applied patch is not mistaken for snapshot drift.

## What is deliberately not in the snapshot

Only tracked files. Build output, `dist/`, `build/`, `release-fomod/` and
anything else ignored upstream are excluded, which is why the whole backup is
about 1.6 MB of source rather than a repository copy.

Line endings are normalised to LF before hashing, so the same commit compared on
a Windows checkout and a Linux one agrees. Without that, `verify` would report
drift on every machine whose git settings differ.