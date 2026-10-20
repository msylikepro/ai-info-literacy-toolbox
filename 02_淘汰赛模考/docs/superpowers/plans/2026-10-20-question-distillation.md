# Question Distillation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Reduce the effective preset bank from 373 to 229 questions while preserving every old question ID, answer record, favorite and exam reference.

**Architecture:** Keep `questions` and its legacy fingerprints. Maintain an alias mapping and `active_questions` view using audited fingerprint groups; unknown imports retain literal HTML, spaces, punctuation and brackets under legacy clean semantics. Only remove empty unanswered duplicate entries from unfinished drill rounds; protect the current item, submitted answers and drafts. Serialize commit imports and alias refreshes before reading question snapshots.

**Tech Stack:** Python standard library, SQLite, Flask, unittest.

**Spec:** Parent task dated 2026-10-20 and `归档管理/题库重复审计_2026-10-20.md`.

## Global Constraints

- Never edit real source or desktop databases or secrets. Use disposable databases and clones for verification.
- Keep question IDs, old fingerprints and historical attempt references unchanged.
- Match answers by selected option content, never by letters.
- Keep years, negation, search expressions, formula symbols and option variants distinct.
- Keep conflicts for review and make import conflicts visible.
- Do not edit packaging or archive cleanup files.

## Review Focus

- Reordered options need answer text remapping.
- Conflicting answers must not disappear behind a duplicate count.
- A current alias with a draft must survive migration unchanged.
- Answered duplicates and historical exam rows must stay intact.
- Fresh seeding, repeated import and existing database migration must agree on 229 active questions.

## Tasks

- [x] Add regression tests and observe expected failures for active count, future imports, conflicts and live-round preservation.
- [x] Add audited data manifest, alias schema, conservative comparison and migration implementation; pass core regression tests.
- [x] Route fresh drills, exam selection, browsing and inventory through active questions; synchronize wrong-question mastery by canonical group.
- [x] Verify historical favorites and exam records, imported conflicts and wrong-round grouping.
- [x] Run the full suite and disposable clone migration checks; record commands and outcomes for parent review.

## Execution evidence

- First regression run: 5 tests, 4 expected failures, 1 existing safeguard passed. New-round/wrong-family tests then failed as expected before implementation; admin conflict visibility also failed before the UI change.
- Frozen mapping contains 140 audited groups and 144 redundant members. New seeding and existing-bank migration both keep 373 physical rows and expose 229 effective questions.
- First full suite: 61 tests passed in 77.45 seconds. A follow-up safeguard test demonstrated that `mid()` must retain its function parentheses; the guarded rule then passed all 8 distillation tests.
- Source SQLite backup was migrated only in a temporary clone: old question/exam columns, favorites, wrong records, submitted feedback and saved drafts stayed unchanged; 2 blank future duplicates were removed; restart was idempotent and integrity_check returned ok. Source file bytes stayed unchanged; the temporary clone was removed.
- Ruling after independent review: use the reviewed fingerprint manifest for all extra preset equivalence. Unknown imports use only legacy clean/NFKC/casefold: the UI renders plain text, so HTML, entities, Chinese spaces, question marks and empty brackets may be literal expressions. Added red tests exposed and then fixed the earlier over-broad normalizer.
- Independent review exposed a concurrent-import race: an older read snapshot could overwrite newly committed aliases. Added two event-controlled, two-connection red tests (direct refresh and duplicate-only commit); both paths now begin an IMMEDIATE write transaction before reading, reusing a caller transaction when present. Read-only preview takes no write lock.
- Ruling: retain differing same-question source rows as aliases, while counting only new effective questions as added. Identical fingerprints stay physically idempotent. Conflicting imports remain in a separate review table and administrator view, retaining the original live answer.
- Parent owns final independent review, package integration and publishing; no commits or release actions are performed by this subtask.
- Final verification after review fixes: 64 tests passed, 0 failures, 0 errors; the 11 distillation tests include quoted/unquoted HTML and entity literals plus both controlled concurrent-import races. Full output is in `docs/题库蒸馏全量回归_2026-10-20.txt`. The real SQLite backup/temporary-clone verification was rerun successfully with the final code.
