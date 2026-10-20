# Merge AI settings save fix into offline release Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan in the current session. Steps use checkboxes for tracking.

**Goal:** Deliver one offline ZIP containing the already-fixed repeated thinking-settings save and the website-name update.

**Architecture:** Preserve all delivered releases. Build v1.4.1 from current source, then create native deltas from v1.0.0 through v1.4.0. The existing chooser routes users to the matching delta and preserves user data.

**Tech Stack:** Python packaging, Windows PowerShell 5.1, C# native updater.

**Spec:** User request in this conversation: merge the AI bug fix from the other conversation into the current offline update. The current source changes `File.Replace`'s backup parameter to `[NullString]::Value`; its UI regression test exercises repeated saves.

## Global Constraints

- Retain v1.4.0 artifacts as an immutable upgrade baseline.
- No personal keys, databases or audit history in public packages.
- Preserve the 196 resource URLs, IDs and associations and current local settings.
- Keep Windows PowerShell scripts encoded UTF-8 with BOM.
- Do not install onto the user's active desktop toolbox.

## Review Focus

- Existing thinking.json: two successive UI saves must work and reopen correctly.
- Already-v1.4.0 folders: select a real 1.4.0-to-1.4.1 patch.
- Interrupted update: route using its base version and keep native recovery checks.
- Existing user data: exercise native rollback, recovery and preservation for all five bases.
- Final ZIP: compare chooser payloads and release manifest to verified files.

### Task 1: Identify and verify the merged fix

- [x] Compare source to packaged v1.4.0; confirm the application change is thinking_config.ps1 only.
- [x] Run the existing repeated-save regression against the old packaged script and confirm failure; against the corrected packaged script confirm success.

### Task 2: Build v1.4.1 and its unified offline package

- [x] Update build defaults, chooser target/support list and packaging descriptions to v1.4.1.
- [x] Extend chooser tests to cover v1.4.0, v1.4.1 and pending journals; run before and after updating the chooser.
- [x] Build a fresh full release and five native deltas; assemble one auto-detecting ZIP with no credential import.

### Task 3: Verify and deliver

- [x] Verify the full ZIP, all five native upgrades and packaged AI UI tests with fake credentials only.
- [x] Check manifests, ZIP checksums and v1.4.0 baseline hash; write evidence and link the new offline ZIP.

## Execution ledger

- Task 1: complete. Existing v1.4.0 repeated-save UI assertion fails; corrected source passes. Original fix left unchanged.
- Task 2: complete. New chooser tests failed against the old target, then all four passed against 1.4.1. Fresh full release, five deltas and unified ZIP built.
- Task 3: five native upgrade and recovery checks pass; portable smoke passes; 24 packaging tests pass. AI suite's first concurrent run had one 20-second timeout; isolated test passed in 2.3 seconds and the sequential full 32-test run passed with unchanged code.
- Independent read-only reviewer found no material issues and confirmed the immutable 1.4.0 baseline, five payload hashes, BOM and public-package contents.
- Task 3: complete. Final artifact audit passes; unified ZIP SHA256 is 0b6d717005f834098edeef7c481f9e5a8c61a3ea30bb075ab76ebaf07f6b3e26, size 1,131,468 bytes. Desktop now reports formal v1.4.0 (updated by the user since the previous turn), and all its program hashes and manifest match the retained v1.4.0 upgrade baseline. Only read-only checks performed.
- Ruling: retain a separate v1.4.1 instead of replacing delivered v1.4.0 — ensures every prior user can apply a reproducible versioned delta.
- Ruling: use the current shared workspace and versioned pristine release folders as isolation — this repository has no committed HEAD, and moving source would detach the other conversation's fix from this build. No source bug rewrite, branch mutation or desktop deployment performed.
