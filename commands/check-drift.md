---
description: "Reads .spec-kit/golden/test-vectors.md and prints a dry-run drift report — one line per vector, prefixed with 'would run:'. No code is executed at this stage."
---

# Golden Demo — Behavioral Drift Check (Dry-Run)

This command runs automatically after `/speckit.implement`. It reads the
test vectors captured during the plan phase and reports what would be
executed in a full behavioral drift check. This is a stub to validate
that the hook fires correctly and that the vector file is reachable.

## Steps

1. Check whether `.spec-kit/golden/test-vectors.md` exists.

   - If the file does not exist, stop and report:
     > "Golden Demo: no test-vectors.md found. Run /speckit.plan first, or
     > install the golden-demo extension before planning."
   - If the file exists but contains no vectors (i.e. the "no criteria
     detected" placeholder is present), stop and report:
     > "Golden Demo: test-vectors.md contains no vectors. Add
     > acceptance criteria to your spec.md and re-run /speckit.plan."

2. Parse the vectors from the `## Vectors` section. Each line starting
   with `- VECTOR` is one vector.

3. For each vector, print exactly this line to the console:

```
would run: {full vector text}
```

4. After all vectors are listed, print a summary:

```
Golden Demo drift check (dry-run): {N} vector(s) identified.
No code was executed. Replace this stub with execution logic to enable
behavioral drift detection.
```

5. Do not modify any files. Do not run any implementation code. Do not
   call any external tools or interpreters.

> **Note:** This step is intentionally inert. Its only purpose is to
> confirm that the `after_implement` hook fires, that the vector file is
> readable, and that the interface is correct. Production execution logic
> (running a reference implementation against real test vectors) is out
> of scope for this draft.
