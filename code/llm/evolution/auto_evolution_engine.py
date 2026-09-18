"""AIOS Autonomous Self-Evolution & Auto-Dev Engine.
Performs continuous AST code audit, automated refactoring, sandbox verification,
and self-healing for the JoTalbot/AIOS codebase.
"""
import os, sys, time, json, ast, subprocess, hashlib
from pathlib import Path
from typing import Dict, Any, List

sys.path.insert(0, '/opt')
sys.path.insert(0, '/opt/aios')

try:
    from aios.llm.llm_balancer import LLMBalancer
    balancer = LLMBalancer.get_instance()
except Exception:
    balancer = None

AIOS_ROOT = Path('/opt/aios')
EVOLUTION_LOG = AIOS_ROOT / 'evolution' / 'evolution_history.json'

def load_evolution_history() -> List[Dict]:
    if EVOLUTION_LOG.exists():
        try:
            return json.loads(EVOLUTION_LOG.read_text(encoding='utf-8'))
        except Exception:
            pass
    return []

def save_evolution_history(history: List[Dict]):
    EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    EVOLUTION_LOG.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding='utf-8')

def audit_codebase() -> List[Dict[str, Any]]:
    """Audits all python modules in AIOS and flags optimization candidates."""
    findings = []
    for py_file in AIOS_ROOT.glob('**/*.py'):
        if '.git' in py_file.parts or 'tests' in py_file.parts or 'venv' in py_file.parts or '__pycache__' in py_file.parts:
            continue
        try:
            code = py_file.read_text(encoding='utf-8')
            tree = ast.parse(code)
            
            # Check function definitions and docstrings
            funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            missing_docs = [f.name for f in funcs if not ast.get_docstring(f)]
            
            findings.append({
                "path": str(py_file.relative_to(AIOS_ROOT)),
                "lines": len(code.splitlines()),
                "functions_count": len(funcs),
                "missing_docstrings_count": len(missing_docs),
                "ast_valid": True
            })
        except Exception as e:
            findings.append({
                "path": str(py_file.relative_to(AIOS_ROOT)),
                "ast_valid": False,
                "error": str(e)
            })
    return findings

def run_evolution_cycle(target_file_rel: str = "evolution/history.py") -> Dict[str, Any]:
    t0 = time.time()
    target_path = AIOS_ROOT / target_file_rel
    if not target_path.exists():
        return {"ok": False, "error": f"File {target_file_rel} not found"}

    code = target_path.read_text(encoding='utf-8')
    print(f"🧬 Starting Self-Evolution Cycle on: {target_file_rel} ({len(code)} bytes)")
    
    prompt = f"""Ты — Ведущий Разработчик автономной ОС AIOS.
Оптимизируй следующий модуль Python: добавь типизацию (Type Hints), строгие docstrings, проверку типов и метод get_summary().

Исходный код:
```python
{code}
```

Верни ТОЛЬКО готовый валидный Python код модуля, без лишнего markdown и без пояснений."""

    if not balancer:
        return {"ok": False, "error": "LLMBalancer not initialized"}

    evolved_code = balancer.generate_sync(prompt, task_type="code")
    # Clean code blocks
    if "```python" in evolved_code:
        evolved_code = evolved_code.split("```python")[1].split("```")[0]
    elif "```" in evolved_code:
        evolved_code = evolved_code.split("```")[1].split("```")[0]
    evolved_code = evolved_code.strip()

    # Sandbox AST validation
    try:
        ast.parse(evolved_code)
        print("  ✅ AST Validation passed!")
    except SyntaxError as e:
        print(f"  ❌ Syntax error in evolved code: {e}")
        return {"ok": False, "error": f"SyntaxError: {e}"}

    # Backup & Write
    backup_path = target_path.with_suffix('.py.bak')
    backup_path.write_text(code, encoding='utf-8')
    target_path.write_text(evolved_code, encoding='utf-8')

    # Run py_compile test
    res = subprocess.run(['/opt/aios-venv/bin/python3', '-m', 'py_compile', str(target_path)], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  ❌ Compile test failed: {res.stderr}")
        target_path.write_text(code, encoding='utf-8') # Rollback
        return {"ok": False, "error": f"Compile test failed: {res.stderr}"}

    print("  ✅ Compile test passed! Evolutionary update applied.")
    backup_path.unlink(missing_ok=True)

    # Record in history
    h_entry = {
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "module": target_file_rel,
        "duration_ms": round((time.time() - t0)*1000, 1),
        "code_sha256": hashlib.sha256(evolved_code.encode()).hexdigest()[:16],
        "status": "evolved_verified"
    }
    history = load_evolution_history()
    history.append(h_entry)
    save_evolution_history(history)

    return {"ok": True, "details": h_entry}

if __name__ == "__main__":
    audit = audit_codebase()
    print(f"Audit completed: {len(audit)} modules analyzed.")
    evo = run_evolution_cycle("evolution/history.py")
    print("Evolution cycle output:", json.dumps(evo, indent=2, ensure_ascii=False))
