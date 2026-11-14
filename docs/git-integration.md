# Integrating ConMan2 with a normal git workflow

Status: concept, 2026-11-14 · Branch `docs/git-integration`

**Goal.** A project repository holds two kinds of content:

- *ordinary files* (code, scripts, documents, configuration, small data). Line-based git works well
  for these.
- *models* (IFC, CityGML / GeoJSON). Line-based git fails for these, and ConMan2's graph-based diff
  and patch is the better fit.

Users should keep working with plain `git` (clone, branch, commit, push, pull requests, CI). Models
should still be diffed, merged, and stored the ConMan2 way.

## 1. Why plain git is not enough for models

| Problem | IFC (STEP P21) | GeoJSON |
|---|---|---|
| Unstable identifiers | `#123` entity ids are renumbered on every export, so almost every line changes | – |
| Order without meaning | entity order in the file depends on the exporter | feature order and property key order |
| Formatting | one entity per line, but references span the whole file | often one single line, or pretty-printed in varying ways |
| Granularity | a line diff shows no objects, attributes, or relations | moving one vertex is a coordinate change in a nested array |
| Merging | textual 3-way merge of STEP files is practically never correct | merging works only by chance |
| Size | 10 MB – 1 GB per version; git keeps full snapshots | city tiles of several MB |

ConMan2 addresses exactly these points. It identifies objects by GlobalId and every other node by a
unique path. Its patches are semantic (attribute changes) and topological (added and removed
structure), and they can be applied in both directions.

## 2. How the concepts map

| git | ConMan2 today | Comment |
|---|---|---|
| commit (SHA) | `timestamp` (free-text version id) | **Use the git blob SHA of the model file as the ConMan2 timestamp.** It is content-addressed and deterministic, and identical models get the same id. |
| commit DAG (`parents`) | `timeline_data/timeline.json` (`commits.parents`) | can be *derived* from `git log -- <model>` instead of being maintained separately |
| branch | `timeline.branches` | git should own branches; the ConMan2 timeline mirrors them |
| delta / pack | `patch_data/Patch_{Topo,Sema}_*.json` | patches are small and diff-friendly JSON, so they can be versioned themselves |
| working tree | the single version in the graph DB | ConMan2 keeps *one* version per project in the DB; git needs random access to any version |
| `fetch` / `pull` / `push` | stubs (`NotImplementedError`) | can be implemented on top of a git remote (see option D) |
| 3-way merge | not available | can be built on patches (see option A2) |

## 3. Integration options

The options build on each other. A and C are read-only or loss-free additions to git. B and D
make ConMan2's history part of the repository.

### A. ConMan2 as git *diff driver* and *merge driver* (lowest friction)

git stays the single source of truth and stores the model files (as LFS objects if they are large).
ConMan2 is called by git through `.gitattributes`:

```gitattributes
*.ifc       diff=conman2 merge=conman2 filter=lfs -text
*.geojson   diff=conman2 merge=conman2
```

```ini
# .git/config (or a repo-local include)
[diff "conman2"]
    command = conman2-git-diff
[merge "conman2"]
    name = ConMan2 graph-based 3-way merge
    driver = conman2-git-merge %O %A %B %P
```

**A1 – diff.** git calls `conman2-git-diff path old-file old-hex old-mode new-file new-hex new-mode`.
The driver parses both files with the **NetworkX provider** (no database needed), runs
`GraphDiffNx` and `GraphPatchNx.create_patch`, and prints a readable summary per object:

```
bldg-0001 (Building)  properties.measuredHeight 23.5 → 24.1, +energyRating "B", −comment
bldg-0002 (Building)  geometry: 1 vertex moved, 1 interior ring removed
bldg-0003 (Building)  added
tree-0003 (SolitaryVegetationObject)  removed
```

`git diff`, `git log -p`, `git show`, and the IDE all show object-level changes. A `textconv`
variant (`[diff "conman2"] textconv = conman2-canonical`) also works in GitHub/GitLab web views if
the canonical form is stored (option C).

**A2 – merge.** git calls the driver with base `%O`, ours `%A`, and theirs `%B`:

1. Diff base→ours and base→theirs. That gives two patches with the same init side (`base`).
2. Detect conflicts on unique paths:
   - the same path with different semantic values,
   - deletion on one side and modification on the other,
   - the same context relation changed differently.
3. Without conflicts, apply both patches one after the other to `base`. This needs a small extension:
   `apply_patch` currently expects the init version to be exactly the DB version. For the second
   patch it has to tolerate nodes created by the first patch, which is a *patch rebase*. Write the
   result to `%A` and exit with 0.
4. With conflicts, write `%A` = ours plus a conflict report (`<file>.conman2-conflicts.json`, listing
   unique path, base, ours, theirs). Exit with 1, and git marks the file as conflicted.

This brings the most important missing feature, merging, to ConMan2 without changing any git
workflow. Pull requests, review, and CI keep working.

### B. Version ConMan2's history *in* the git repository (hooks)

The model file stays in git (possibly LFS), and ConMan2's artefacts are committed next to it:

```
project/
├── models/arc.ifc                  # the model (LFS)
├── .conman2/
│   ├── timeline.json               # derived from git, see below
│   └── patches/Patch_{Topo,Sema}_<project>_<blobA>_<blobB>.json
└── .gitattributes
```

- A **pre-commit hook** looks at staged model files and computes the patch against the model's
  version in `HEAD` (`git show HEAD:models/arc.ifc`) with the NetworkX provider. It stages the
  patch. The ConMan2 timestamp is the blob SHA (`git hash-object`).
- A **post-checkout / post-merge hook** brings an optional Neo4j cache to the checked-out version
  with `conman2 checkout`. The model file itself is already in the working tree, written by git.
- `timeline.json` no longer has to be maintained by hand. It is generated from
  `git log --format='%H %P' -- models/arc.ifc`, and branches come from `git branch --contains`.

Effect: the full semantic history travels with every clone, push, and fork, and queries like
"when did `measuredHeight` of `bldg-0001` change?" are answered from the patches without parsing
old snapshots. Optionally, the model snapshots can later be thinned out to every n-th version
(keyframes plus patches, like video codecs). That requires P1-style robust patches.

### C. Canonicalisation via clean/smudge filters

```gitattributes
*.geojson filter=conman2-canonical
```

```ini
[filter "conman2-canonical"]
    clean  = conman2-canonical --stdin
    smudge = cat
```

`clean` stores the model in a canonical, diff-friendly form:

- **GeoJSON:** `GeoJsonGraphInterface.graph_2_geojson` already writes RFC member order, sorted
  property keys, and deterministic indentation. Additionally, one feature per line or block, and
  features sorted by id (if order carries no meaning).
- **IFC:** deterministic renumbering of STEP ids (e.g. ordered by GlobalId and unique path) and a
  fixed attribute serialisation, so unchanged entities keep their line.

After this, even the plain line diff becomes meaningful, and textual merges succeed much more often.
C is a cheap complement to A, and it helps every git tool (blame, web UI).

### D. Object-level decomposition (one file per object)

The (unmerged) branch `textbasedDiff` already contains an `IfcDecomposer` that splits an IFC file
into per-object chunk files (`<GlobalId>_<Name>.pifc`). The same applies to GeoJSON:
`features/<id>.geojson` plus a `collection.json` holding the foreign members.

- git diffs, blames, and merges *per object*. Conflicts only arise when the same object is changed
  on both sides. Sparse checkout of parts of a city or building becomes possible.
- ConMan2 recomposes the full model (`conman2 compose`) for tools that need one file.
- Identity is provided by file names (GlobalId / feature id) and therefore matches ConMan2's
  PrimaryNodes. Everything below an object stays in the chunk and is matched by ConMan2's paths.

### E. `fetch` / `pull` / `push` on top of a git remote

The stubs in `command_line_interface/{Fetch,Pull,Push}.py` can use a git remote as transport. Patches
and `timeline.json` (option B) are plain files, so `push` is `git push` of the `.conman2/` content.
`pull` is `git pull` followed by `conman2 checkout` to the new head, using the merge driver from A2.
A dedicated server protocol is not needed.

## 4. What goes where

| Content | Storage | Diff / merge |
|---|---|---|
| source code, scripts, docs, configuration | git | git |
| small GeoJSON / CityJSON (< ~5 MB) | git (canonicalised, C) | ConMan2 driver (A) |
| IFC models, large city tiles | Git LFS | ConMan2 driver (A); history as patches (B) |
| ConMan2 patches, timeline | git (`.conman2/`) | git (they are JSON) |
| graph DB (Neo4j), `networkx_graph_*.gpickle` | **not** in git: a cache, rebuilt from model + patches | – |
| derived exports (`get` output) | not in git (build artefacts) | – |

`.gitignore` additions for repositories using ConMan2:

```gitignore
networkx_graph_*.gpickle
networkx_equivalence_*.json
.env
```

## 5. Recommended roadmap

1. **Diff driver (A1)**, read-only and risk-free. It uses the NetworkX provider, so there is no
   database dependency. That provider has full diff/patch on the feature branches (`GraphDiffNx`,
   `GraphPatchNx`). Deliverables: `conman2-git-diff` entry point, `.gitattributes` template, and a
   readable change summary (proposal P8 in `docs/GeoJSON_CityGML_DiffPatch.md`).
2. **Canonical form (C)** for GeoJSON, which is nearly free with the existing exporter. Then for IFC.
3. **Blob SHA as timestamp, timeline derived from `git log` (B)**. This removes the second, manually
   maintained history.
4. **Merge driver (A2)**: conflict detection on unique paths plus patch rebase.
5. **Decomposition (D)** for very large models and team collaboration on parts of a model.

## 6. Prerequisites in ConMan2 and open questions

- **Determinism.** The same input must produce the same graph and the same patch. For GeoJSON this is
  ensured (structural `p21_id`s, sorted output). For IFC, `graph_2_ifc` assigns new STEP ids, which
  matters for option C.
- **No global state.** CLI commands write `timeline_data/` and `patch_data/` into the current
  directory, and `Neo4jConnection` is configured at import time. Drivers and hooks need explicit
  paths (`--repo`, `--patch-dir`), and must not have side effects on import.
- **"One version in the DB" invariant.** git needs random access to arbitrary versions. Drivers
  should therefore use NetworkX in-memory graphs. Neo4j remains an optional query cache.
- **Speed.** Diff drivers run on `git log -p` for every commit. NetworkX is fast enough (≈ 0.1 s for
  1.3k nodes). The Neo4j path is not (≈ 20 s).
- **Several models per repository** and file renames. Project identity comes from the IfcProject
  GlobalId or the FeatureCollection id, not from the path. That is correct, but hooks have to map
  path → project.
- **Patch robustness.** A rebase in A2 requires patches that tolerate small deviations in the init
  version. Strict path resolution (it raises instead of silently picking the wrong node) is the
  safe default for this.
