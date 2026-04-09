import ast
import os
from pathlib import Path

def parse_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        try:
            tree = ast.parse(f.read(), filename=str(filepath))
        except Exception as e:
            return f"Error parsing: {e}"
            
    docs = []
    
    module_doc = ast.get_docstring(tree)
    if module_doc:
        docs.append(f"**Module Docstring:** {module_doc.split(chr(10))[0]}")
    
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    for c in classes:
        doc = ast.get_docstring(c)
        doc_str = doc.split(chr(10))[0] if doc else "No docstring"
        docs.append(f"- **Class `{c.name}`**: {doc_str}")
        # Methods
        methods = [n for n in c.body if isinstance(n, ast.FunctionDef)]
        for m in methods:
            if m.name.startswith('_') and m.name != '__init__': continue
            mdoc = ast.get_docstring(m)
            mdoc_str = mdoc.split(chr(10))[0] if mdoc else ""
            if mdoc_str:
                docs.append(f"  - `def {m.name}()`: {mdoc_str}")
            else:
                 docs.append(f"  - `def {m.name}()`")
                 
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    for f in functions:
        if f.name.startswith('_'): continue
        doc = ast.get_docstring(f)
        doc_str = doc.split(chr(10))[0] if doc else "No docstring"
        docs.append(f"- **Function `{f.name}()`**: {doc_str}")
        
    if not docs:
        return "*No public classes or functions found.*"
    return "\n".join(docs)

def sync_directory(dir_path):
    p = Path(dir_path)
    if not p.exists() or not p.is_dir(): return
    
    index_file = p / "index.md"
    if not index_file.exists():
        # Only sync dirs that have qualitative indexes
        return
        
    # Find active py files (ignore subdirectories for this shallow index)
    py_files = list(p.glob("*.py"))
    
    with open(index_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    marker = "<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->"
    if marker in content:
        top_half = content.split(marker)[0]
    else:
        top_half = content + "\n\n"
        
    bottom_half = [marker]
    bottom_half.append("\n## Auto-Generated Code Reference\n")
    bottom_half.append("*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*\n")
    
    for py in sorted(py_files):
        if py.name == "__init__.py": continue
        bottom_half.append(f"### `{py.name}`")
        parsed = parse_file(py)
        bottom_half.append(parsed)
        bottom_half.append("")
        
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write(top_half + "\n".join(bottom_half))
    print(f"Synced {index_file}")

DIRS_TO_SYNC = [
    "engines/engine_a_alpha",
    "engines/engine_b_risk",
    "engines/engine_c_portfolio",
    "engines/engine_d_research",
    "engines/data_manager",
    "orchestration",
    "scripts"
]

if __name__ == "__main__":
    for d in DIRS_TO_SYNC:
        sync_directory(d)
