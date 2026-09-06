# Changelog

## [Unreleased]

### Fixed

- Build the installation wheel directly from the checkout, avoiding misleading
  Git-discovery errors from an unnecessary source-archive round-trip.
- Prepare new batches under a temporary name and publish complete directories
  atomically without replacing existing destinations, so interrupted setup can
  be retried. Preserve writer locks across publication and reject unsupported
  exclusive-rename operations.
- Exclude translated caption URLs even when yt-dlp returns them while translation
  extraction is disabled, preserving native-only discovery and language selection.
- Match source-checkout version inference to build settings for untagged repositories.

### Added

- Installable `ytt-dl` command for single or multiple YouTube URLs and video IDs,
  including input files and stdin.
- English-first caption selection, explicit language fallbacks, optional
  timestamps, track discovery, and structured JSON results.
- Named folders beneath `~/ytt-dl` or a custom output root, with a separate text
  file for each successful video.
- Stable batch identities, safe reruns, explicit overwrite control, atomic file
  publication, process locks, and interruption recovery.
- Bounded network retries, per-video failures, and sanitized diagnostics.
- Locked uv development and installation, offline tests, package validation,
  and macOS/Linux CI configuration.

### Changed

- Consolidated the original shell/download/build/verification pipeline into one
  Python application. The new application retrieves one selected JSON3 caption
  track and does not require a separate VTT download.
