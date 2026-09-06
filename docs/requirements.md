<!-- markdownlint-disable MD001 MD024 -->
<!-- markdownlint-disable-next-line MD013 -->
<!-- maintain-project-specs:requirements:start schema=maintain-project-specs/requirements-v2 -->
# Project Requirements

These records cover batch initialization, interruption recovery, and checkout
installation. The README documents the complete command interface and transcript
behavior.

<!-- REQUIREMENT: REQ-001 status=satisfied priority=P2 type=feature -->
### REQ-001: Interrupted batch initialization permits a safe rerun

#### User Story

A user whose download stops during folder setup can rerun the same ordered video
inputs without an incomplete final folder blocking the command.

#### Acceptance Criteria

- AC-001: New final batch folders appear only after their schema-v1 manifest and
  text-files directory are prepared. Transcript publication starts afterward.
- AC-002: Process interruption before or after final-folder publication permits
  an identical rerun when there is no unrelated destination collision.
- AC-003: Publication never replaces an existing destination, including an empty
  directory, file, or symlink created by a competing writer.
- AC-004: The existing batch writer lock remains effective across publication
  and is released when the process exits.
- AC-005: Unsupported exclusive-rename operations fail without publishing an
  incomplete final folder or falling back to an overwriting rename.

#### Negative Criteria

- NC-001: Do not adopt, delete, or modify pre-existing unidentified directories
  or abandoned staging directories. A name alone is not proof of ownership.
- NC-002: Do not change manifest schema, output naming, CLI options, caption
  selection, or transcript replacement rules.
- NC-003: Process-interruption tests do not establish power-loss durability or
  support for every network filesystem.

#### Validation Method

Use synthetic local batches on supported macOS and Linux filesystems. Inject
failures at initialization boundaries and independently inspect paths and
manifests before retrying. Keep source, installed-package, and platform evidence
separate.

#### Test Method

Storage regression tests cover interrupted setup and destination races.
Separate-process tests terminate writers before and after publication and
exercise the retained batch lock.

#### Evaluation Method

The original before-manifest failure must fail against the old implementation
and pass after repair. Every exercised rerun must retain its identity, and every
foreign destination must retain its original contents and filesystem identity.

<!-- /REQUIREMENT: REQ-001 -->

<!-- REQUIREMENT: REQ-002 status=satisfied priority=P2 type=bug -->
### REQ-002: Checkout installation avoids unnecessary Git-discovery errors

#### User Story

A user running `make install` from a valid Git checkout receives a working
command without misleading Git-discovery errors from an intermediate archive.

#### Acceptance Criteria

- AC-001: Build the installation wheel directly from the checkout, preserving
  SCM-derived version metadata and runtime constraints from `uv.lock`.
- AC-002: The installer completes without the reported Git file-listing error;
  the installed command provides working help and the expected version.
- AC-003: `make build` retains source-archive and wheel validation.

#### Negative Criteria

- NC-001: Do not suppress diagnostic output, disable SCM discovery globally,
  change dependency versions, or hide a real build failure.
- NC-002: Do not change command options or transcript behavior.

#### Validation Method

Compare the default archive-to-wheel build with direct wheel construction using
the locked toolchain. Run the actual installer in a disposable checkout and
isolated tool environment.

#### Test Method

Capture installer output and exit status, inspect the installed command's help
and version, and check that the source lockfile remains unchanged.

#### Evaluation Method

The installation regression must detect the original error before repair and
pass afterward. Retain source-archive verification as a separate packaging check.

<!-- /REQUIREMENT: REQ-002 -->
<!-- maintain-project-specs:requirements:end -->
<!-- markdownlint-enable MD001 MD024 -->
