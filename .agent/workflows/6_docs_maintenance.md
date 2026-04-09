---
description: Maintain and refresh the hybrid architectural documentation
---
# Documentation Maintenance Workflow
This workflow ensures that the qualitative architectural summaries remain perfectly in sync with the dynamically moving codebase. 

// turbo-all
1. Run the documentation syncer to automatically update the code reference AST tables:
   ```bash
   python scripts/sync_docs.py
   ```
2. The AI will read the newly synced `index.md` files and compare the `Auto-Generated Code Reference` against the human-written top-half.
3. If new classes, scripts, or architectural patterns have emerged that are undocumented, the AI will rewrite the qualitative summary to include them and ask for approval.
