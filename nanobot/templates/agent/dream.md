Update memory files by analyzing conversation history and editing files directly.
Prune before adding — removing stale content is as important as adding new facts.

## Lifecycle
- At the start of the batch, call `long_task` with goal: "Consolidate unprocessed memory backlog into MEMORY.md, SOUL.md, USER.md".
- After all edits are done, call `complete_goal` with a short recap of what was changed.

## File routing
Do NOT guess paths. Route each fact to its canonical file:

| File | Full path | Content |
|------|------|---------|
| SOUL.md | `{{ soul_path }}` | Agent behavior, guardrails, tone, interaction patterns |
| USER.md | `{{ user_path }}` | Personal info, preferences, habits, work context, communication style |
| MEMORY.md | `{{ memory_path }}` | Technical knowledge, project context, infrastructure, accounts |
| SKILL.md | `skills/<name>/SKILL.md` | Reusable workflow templates ([SKILL] entries only) |

Cross-boundary rule: no technical configs in USER.md, no user facts in SOUL.md, no preferences in MEMORY.md. If a fact fits multiple files, keep the most specific copy and remove the rest.

## Delete-or-keep

**Always delete:**
- Same fact at multiple locations — keep canonical copy only
- Merged/closed PR notes, resolved incidents, superseded info
- Verbose entries restatable in fewer words
- Overlapping or nested sections covering the same topic

**Likely delete** (apply judgment):
- Same fact at different detail levels — keep most complete version only
- Debugging steps unlikely to recur
- Ephemeral facts past their useful life
- Tool/service details documented upstream
- Entries no longer referenced in recent conversations or superseded by newer facts — closer review, not automatic removal

**Never delete:**
- User preferences and personality traits (permanent regardless of age)
- Active project context still referenced in conversations
- Behavioral rules in SOUL.md

When removing: prefer deleting individual items over entire sections.

## Fact extraction
- Atomic facts: "has a cat named Luna" not "discussed pet care"
- Corrections: edit the existing entry, don't append a new one
- Capture confirmed approaches the user validated

## Skill discovery & creation
Flag [SKILL] only when ALL are true: repeatable workflow appeared 2+ times, involves clear steps (not vague preferences), substantial enough for its own instruction set. Check existing skills to avoid redundancy.

For [SKILL] entries:
- Use write_file to create skills/<name>/SKILL.md; read_file `{{ skill_creator_path }}` for format reference
- YAML frontmatter (name, description), under 2000 words: when to use, steps, output format, example
- Do NOT overwrite existing skills — if overlapping, merge delta into the existing skill
- Skills are instruction sets, not code. Keep concrete values in MEMORY.md; skills use placeholders

## Editing
- Default tool: apply_patch. Use edit_file only for small exact replacements.
- Use read_file to inspect current file contents before editing; they are not embedded in the prompt to keep context compact.
- Batch all changes into a single apply_patch call. Surgical edits only.

Do not add: current weather, transient status, temporary errors, conversational filler.
