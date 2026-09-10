from pathlib import Path
import re

p = Path("app/services/plan_satisfaction.py")
t = p.read_text(encoding="utf-8")
# Collapse accidental blank lines between statements (file got double-spaced somehow)
if t.count("\n\n") > t.count("\n") * 0.4:
    lines = t.splitlines()
    # Only undouble if most lines are empty-alternating
    nonempty = [ln for ln in lines if ln.strip()]
    if len(lines) > 1.5 * len(nonempty):
        t = "\n".join(nonempty) + "\n"
        p.write_text(t, encoding="utf-8")
        print("normalized double-spacing")
        t = p.read_text(encoding="utf-8")

pat = re.compile(
    r'if len\(rows\) == lim and len\(counts\) == 1 and "each" in \(question or ""\)\.lower\(\):\s*'
    r'# Classic failure: top-N overall instead of per partition\s*'
    r'warnings\.append\("partitioned top-n collapsed to a single overall top-n result"\)',
    re.M,
)
repl = (
    'if (\n'
    '                len(rows) == lim\n'
    '                and len(counts) == 1\n'
    '                and "each" in (question or "").lower()\n'
    '                and sql\n'
    '                and "PARTITION BY" not in sql.upper()\n'
    '            ):\n'
    '                warnings.append("partitioned top-n collapsed to a single overall top-n result")'
)
t2, n = pat.subn(repl, t, count=1)
if n:
    p.write_text(t2, encoding="utf-8")
    print("partition gate fixed", n)
else:
    print("pattern not found; snippet:")
    idx = t.find("collapsed to a single overall")
    print(repr(t[idx-200:idx+120]) if idx >= 0 else "missing")
