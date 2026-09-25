# Applying this licensing pack to the StygNox repository

This archive is deliberately conservative: it provides repo-ready legal/community files plus snippets for files that may already exist.

## 1. Inspect before copying

From the StygNox repository root, extract the archive somewhere temporary first:

```bash
mkdir -p /tmp/stygnox-licensing-pack
tar -xzf stygnox-licensing-pack-v1.tar.gz -C /tmp/stygnox-licensing-pack
find /tmp/stygnox-licensing-pack -maxdepth 3 -type f -print | sort
```

## 2. Check the current repository licence

```bash
git status --short
find . -maxdepth 2 -type f \
  \( -iname 'license*' -o -iname 'copying*' -o -iname 'notice*' -o -iname '*contribut*' \) \
  -print | sort
```

If `LICENSE`, `CONTRIBUTING.md`, trademark terms or an existing CLA already exist, review them rather than blindly overwriting them.

## 3. Copy the core files

Assuming you intend to replace the existing project licence and have confirmed that the repository is currently entirely yours:

```bash
PACK=/tmp/stygnox-licensing-pack/stygnox-licensing-pack-v1

cp "$PACK/LICENSE" ./LICENSE
cp "$PACK/LICENSING.md" ./LICENSING.md
cp "$PACK/COMMERCIAL-LICENSING.md" ./COMMERCIAL-LICENSING.md
cp "$PACK/CLA.md" ./CLA.md
cp "$PACK/RECOGNITION.md" ./RECOGNITION.md
cp "$PACK/CONTRIBUTORS.md" ./CONTRIBUTORS.md
cp "$PACK/CREDITS.md" ./CREDITS.md
cp "$PACK/CONTRIBUTING-LICENSING.md" ./CONTRIBUTING-LICENSING.md
cp "$PACK/TRADEMARK.md" ./TRADEMARK.md
cp "$PACK/NOTICE.md" ./NOTICE.md
mkdir -p docs/legal
cp "$PACK/docs/legal/SOURCE-HEADER.md" ./docs/legal/SOURCE-HEADER.md
```

## 4. Merge rather than overwrite existing project guidance

Use `README-LICENSING-SNIPPET.md` to update the existing README.

If the repository already has a pull-request template, merge `.github/PULL_REQUEST_TEMPLATE-LICENSING-SNIPPET.md` into it rather than replacing it.

Only enable `.github/FUNDING.yml` after inserting real funding account details.

## 5. Review

```bash
git status --short
git diff --stat
git diff -- LICENSE LICENSING.md COMMERCIAL-LICENSING.md CLA.md \
  RECOGNITION.md CONTRIBUTORS.md CREDITS.md CONTRIBUTING-LICENSING.md \
  TRADEMARK.md NOTICE.md docs/legal/SOURCE-HEADER.md
```

Confirm that:

- `LICENSE` is the unmodified GNU AGPL v3 licence text;
- project-facing files consistently say `AGPL-3.0-only`;
- no previous third-party contributor has copyright in code being relicensed without permission;
- any dependencies, vendored code or bundled assets retain their own licences;
- the commercial licensing contact/funding mechanism is configured the way you want.

## 6. Suggested commit

```bash
git add LICENSE LICENSING.md COMMERCIAL-LICENSING.md CLA.md \
  RECOGNITION.md CONTRIBUTORS.md CREDITS.md CONTRIBUTING-LICENSING.md \
  TRADEMARK.md NOTICE.md docs/legal/SOURCE-HEADER.md

git commit -m "adopt AGPL-3.0-only dual-licensing and contributor model"
```

Add README / PR-template / funding changes to the same commit only after merging the supplied snippets into the repository's existing files.

## Legal review checkpoint

The standard AGPL text should remain unchanged. The custom CLA, commercial licensing policy and trademark policy are project-specific documents and should receive professional legal review before they are relied on for a significant commercial agreement or dispute.
