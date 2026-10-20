# Project rules

- This standalone repository is `Tiachi/video-sft-builder`, private, with stable branch `main`. Task branches use `codex/<description>`.
- Read `docs/decisions.md` and `configs/project.example.json` before changing the design. Runtime configuration with null values is incomplete, not permission to guess.
- Current scope: Linux execution, MP4-only visual input, LLaVA three-level captions, General and Long candidate synthesis, CoT strategy pending, one combined visual audit. No A4 or A10. Quality failure/uncertainty goes to reject without repair, rewatch, or regeneration.
- User ratios are global targets by accepted record count: zh/en=3/7, oe/mcq=7/3, MCQ option counts 3/4/6=1/7/2. General/Long mixture is unspecified. Do not claim exact small-batch ratios or restore rejected records to satisfy quotas.
- Store only reviewed code, configuration templates, tiny synthetic test fixtures and durable documentation in Git. No datasets, media, archives, model weights, full logs, caches, credentials, real environment files or signed URLs.
- Original media is immutable. Derived artifacts live outside the checkout. Record detailed audit/lineage outside the final training JSON; keep its 12 top-level fields.
- Preserve unrelated work. Stage exact paths. No auto-stash, reset, clean or force-push. Require a clean main checkout and fast-forward-only updates; verify GitHub and local commit SHA.
- Complex server operations must be repository scripts, reviewed and tested locally, committed and synchronized through GitHub first. Never ask for long pasted heredocs or strict mode in the user's long-lived shell.
- Distinguish documented, proposed, implemented, locally verified and server runtime verified. Current data-producing pipeline is not implemented.
