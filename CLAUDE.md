@AGENTS.md

## Notes for Claude Code

- The agent skill that ships in the wheel lives in `skills/pairbench/`. The folder
  `.claude/skills/pairbench` is a link to it, so Claude Code loads the same skill in this
  repository; edit the files under `skills/pairbench/`.
- A change is ready when every command under "Set up, test and lint" in AGENTS.md passes.
- When you describe a result, use the tool's own words: FASTER, SLOWER, BETTER, WORSE,
  HIGHER, LOWER, TIE, UNRESOLVED or NO VERDICT, with the case, the ratio, the noise bar and the
  p-value. The rules are in `skills/pairbench/references/wording.md`.
- The JSON Schemas of the capture, results, config and diagnostics documents are in
  `src/pairbench/results/schema/`; `pairbench schema results` prints the results schema.
