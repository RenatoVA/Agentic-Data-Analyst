# Workspace Conventions

- Keep raw uploads immutable whenever possible. Prefer writing derived outputs into subfolders such as `analysis/`, `reports/`, or `generated_plots/`.
- Name generated files so that a human can understand what they contain.
- Prefer concise reports over verbose dumps.
- If you create multiple artifacts in one workflow, mention the relationship between them clearly.
- When a cleaning or export action requires approval, explain the exact output path that will be created.
