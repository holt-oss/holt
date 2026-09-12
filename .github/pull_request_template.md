## What changed

<!-- Describe the user-visible behavior. Keep implementation detail below it. -->

## Why

<!-- Link the issue or evidence that motivates this change. -->

## How it was verified

<!-- Paste commands and their terminal results. Report skipped tests explicitly. -->

```text

```

## Evidence and boundaries

<!--
Does this change what data Holt reads, what a model sees, how evidence ids
resolve, where the temporal cutoff applies, or how a verdict is computed?
Write "No boundary changes" when none apply.
-->

## Checklist

- [ ] The change is focused and has tests appropriate to its risk.
- [ ] `uv run pytest -rs` passes, and any skips are explained above.
- [ ] User-facing commands, output, and guarantees are documented.
- [ ] New fixtures or recordings are public, necessary, and redacted.
- [ ] No credentials, private repository data, or unrelated generated files are included.
- [ ] I have the right to submit this work under Apache-2.0.
