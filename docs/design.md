<!-- markdownlint-disable MD001 MD024 -->
<!-- markdownlint-disable-next-line MD013 -->
<!-- maintain-project-specs:design:start schema=maintain-project-specs/design-v2 -->
# Project Design

<!-- markdownlint-disable-next-line MD013 -->
<!-- FEATURE: FEAT-001 reqs=REQ-001 status=ready delivery=verified priority=P2 version=1 -->
### FEAT-001: Prepare and exclusively publish batch directories

#### Requirements Covered

- REQ-001: Interrupted batch initialization permits a safe rerun.

#### Context Evidence

`storage.open_batch` creates the final directory before `Batch.save(new=True)`.
An interruption before that save leaves no manifest; subsequent single-video
discovery ignores the folder, but creation rejects its occupied name. Moving the
same interruption after the manifest save permits a rerun. Existing transcript
publication and advisory locks already belong to `storage.py`.

#### Design Details

While holding the existing root lock, create a unique
`.ytt-dl-init-<uuid>.tmp` child under that same root. Open its directory descriptor
and acquire its batch lock. Create and synchronize text-files, then save the
initial manifest using the existing atomic file publisher, which also
synchronizes the containing directory.

Publish the prepared directory using a descriptor-relative native exclusive
rename: `renameatx_np` with `RENAME_EXCL` on macOS, or `renameat2` with
`RENAME_NOREPLACE` on Linux. Synchronize the parent afterward. Keep the same
directory, text-directory, and batch-lock descriptors across the rename. The
batch becomes available to the service only after this sequence completes.

An existing destination causes a conflict without replacement. Missing native
support or an unsupported filesystem causes a clear operational failure; there
is no ordinary-rename fallback. No external package is required: the native
calls use Python's standard-library ctypes with explicit argument/result types.

Discovery ignores staging names, including completed but unpublished stages.
Failures may leave a small hidden stage containing only initialization files;
it is neither adopted nor automatically deleted. After successful publication,
any interruption leaves the complete final directory available for discovery.
Already-stranded final folders from older runs remain protected conflicts.

Native API references: [Apple rename documentation](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/man/man2/rename.2),
[Apple flags](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/bsd/sys/stdio.h),
[Linux rename documentation](https://man7.org/linux/man-pages/man2/rename.2.html),
and [Linux flags](https://raw.githubusercontent.com/torvalds/linux/master/include/uapi/linux/fs.h).

#### Selected Option

Use staging plus exclusive publication in the existing storage owner. It makes
initialization retryable without interpreting unidentified existing folders.
The Python, filesystem, CLI, and manifest technologies remain fixed.

#### Alternatives Considered

- Direct final-folder creation preserves the proven interruption window.
- Exception cleanup cannot run after abrupt process death.
- Adopting or deleting manifestless folders assumes ownership without evidence.
- Ordinary rename can replace an empty directory created by another writer.

#### Implementation Boundaries

Change `storage.py`, focused storage/process tests, README, and changelog. Retain
the service/CLI boundary, manifest schema, transcript publication, and existing
root/batch lock scope. No migration, dependency change, or live output cleanup.
Design review focuses on atomicity, ownership, lock continuity, and failure
behavior; there is no AI subsystem or stack-selection work.

#### Test-First Success Criteria

- TDD-001: Interruption before the initial manifest leaves no final destination,
  and the identical rerun succeeds; the old implementation must fail this test.
- TDD-002: Publication never replaces a racing foreign destination.
- TDD-003: Abrupt process death on either side of publication permits recovery.

#### Validation Plan

Run focused storage and process tests, then all offline unit tests and affected
process integration tests. Run Ruff, Markdown lint, and diff checks. Inspect
platform-specific behavior and report unexecuted platforms separately.

#### Test Plan

Cover initial manifest failures, before/after rename interruption, parent-sync
failure, complete abandoned stages, existing and racing destination types,
unsupported primitives, unchanged inode/lock identity, and real process death.

#### Evaluation Plan

Independent path/manifest inspection and a fresh successful rerun establish
recovery. Tests must not pre-create a manifest or remove blockers to satisfy the
repair oracle. Retain existing rerun, overwrite, and concurrent-writer checks.

#### Rollout And Rollback

Run the updated source command or reinstall after validation. Existing valid
batches continue through their established path; no data migration is needed.
Reverting the source restores the prior initialization risk. Never remove user
outputs as part of rollout or rollback. Power-loss and network-filesystem
durability remain outside process-interruption evidence.

#### Done Definition

The source repair, original regression, affected-boundary tests, and alignment
checks pass; implementation and platform verification evidence are recorded.

#### Implementation Evidence

`Directory.publish_directory` implements the two native exclusive-rename paths
with explicit ctypes signatures and unsupported-operation errors. `open_batch`
prepares and synchronizes the initial structure under a unique staging name,
then publishes it while retaining its open descriptors and writer lock.
README and changelog describe recovery and the protected ownership boundary.

#### Verification Evidence

The original before-manifest interruption test failed against the prior source
because the incomplete final folder already existed. It passes after repair;
the baseline after-manifest counterfactual also succeeds.

On macOS with Python 3.13, all 120 offline unit and affected process tests pass.
On Linux with Python 3.12 in a local container, all 40 storage and process tests
pass using the actual Linux rename operation on tmpfs. The container uses
read-only source/dependency mounts, no network, and no package installation.

Coverage includes single/batch process death at three initialization boundaries,
CLI interruption and rerun, foreign destination type/race preservation, parent
synchronization failure, abandoned stages, native call signatures, unsupported
operations, and writer-lock exclusion/release. The source checks establish
process-interruption recovery on these exercised platforms. Installed-package
activation, remote CI, hardware power loss, and other filesystems were not
validated by these trials.

<!-- /FEATURE: FEAT-001 -->

<!-- markdownlint-disable-next-line MD013 -->
<!-- FEATURE: FEAT-002 reqs=REQ-002 status=ready delivery=verified priority=P2 version=1 -->
### FEAT-002: Build the installation wheel directly from the checkout

#### Requirements Covered

- REQ-002: Checkout installation avoids unnecessary Git-discovery errors.

#### Context Evidence

The installer invokes build 1.6.0 without a distribution selector. Its default
builds a source archive, then a wheel from the extracted archive. During wheel
dependency discovery and wheel construction, setuptools-scm 9.2.2 attempts Git
file discovery without Git metadata and logs the reported error. Both builds
finish successfully. A direct wheel build produces no such diagnostic.

#### Design Details

Add `--wheel` to the installer's existing `python -m build` invocation. Keep the
locked sync, fresh temporary output directory, single-wheel check, runtime
constraints export, and isolated tool reinstall. Genuine failures keep their
existing nonzero exit and diagnostic output.

The separate `make build` target retains the default archive-to-wheel path to
validate distributable source contents. The documented
[build CLI](https://build.pypa.io/en/stable/reference/cli.html) supports both paths.

#### Selected Option

Select the artifact needed for installation at the existing installer boundary.
This is a localized repair; no application architecture or public API changes.

#### Alternatives Considered

- Suppressing errors or disabling SCM file discovery obscures real failures.
- Changing build dependencies is unnecessary for direct wheel installation.
- Changing `make build` would remove its source-archive completeness check.

#### Implementation Boundaries

Change the installer build selection, installation regression tests, README,
and changelog. Retain the dependency lock, build backend, full distribution
build, and application source unchanged.

#### Test-First Success Criteria

- TDD-001: The actual installer completes without the Git-discovery signature
  and installs a command with working help and the checkout's expected version.

#### Validation Plan

Run the installation regression before and after repair, installer help tests,
shell syntax/lint, and Markdown checks. Verify the normal installer entry point.

#### Test Plan

Use a disposable tagged Git checkout and isolated uv tool/bin directories.
Capture output without filtering build diagnostics; preserve the lockfile.

#### Evaluation Plan

An unchanged pre-repair installer must fail the diagnostic assertion despite
exiting successfully. The repaired installer must satisfy all assertions.

#### Rollout And Rollback

Use the updated checkout's `make install`. Reverting the selector restores the
unnecessary archive round-trip. Neither operation changes transcript outputs.

#### Done Definition

The original diagnostic is absent from the repaired installation, the installed
command runs, and packaging guarantees and relevant documentation remain aligned.

#### Implementation Evidence

The installer now passes `--wheel` to its existing build command. Its locked
dependency and installation flow is unchanged. README and changelog distinguish
checkout installation from the full source-archive validation build.

#### Verification Evidence

The default build reproduced the message twice and exited zero. The direct
wheel counterfactual exited zero with no such message and contained the current
application source. The actual installer regression failed before repair on the
exact diagnostic assertion, despite successful installation. It passes after
repair with working installed help, tagged version, unchanged lockfile, and
temporary-artifact cleanup in an isolated tool environment.

On macOS with Python 3.13, all eight installer, installer-help, and SCM-version
tests pass. A normal `make install` from the working checkout also exits zero,
prints no Git-discovery or ERROR lines, and leaves the lockfile unchanged. The
installed command's help and version both run successfully. Shell syntax,
ShellCheck, Ruff, Markdown lint, canonical-pair validation, and a read-only
review pass. Linux installer execution and remote CI were not run in this repair;
the verified end-to-end scope is the exercised macOS installation.

<!-- /FEATURE: FEAT-002 -->
<!-- maintain-project-specs:design:end -->
<!-- markdownlint-enable MD001 MD024 -->
