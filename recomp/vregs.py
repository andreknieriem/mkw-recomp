"""Function-local FP/SIMD registers for recomp/gen.py (as recomp/regs.py does for X0-X30).

The lifted code reads and writes V0-V31 in the Cpu (c->v[n], through the register macros of runtime/cpu/simd.h), so
every FP instruction loads and stores memory: guest stores go through may_alias pointers that may alias the Cpu, and
the C compiler cannot keep a V register in a host register across them. The hottest function of the race
(main+0x1f7720, 1.8.0) is 54k x86 instructions with 17.6k memory operands, most of them V registers.

A generated function whose every V access is one of the forms below gets a local array instead (`u128 V[32]`, the
macros of runtime/cpu/simd_vloc.h index it), loaded at its entry with the registers it uses and synced with the Cpu
where regs.py syncs X registers: before a call, an SVC, a trap, a return or a tail exit it stores the registers it
touched since the last sync, and after a call or an SVC it loads them all again (the callee may change any V register:
AAPCS64 keeps only the low halves of V8-V15). Constant indices let clang's SROA keep each element in a host register.
Every other function keeps `V` pointing at c->v, which is the code as it was.

The forms: c->v[N] in the lifted C; VREG, VQ, VW, VS8..VSF64, VHI64, FP_SETS, FP_SETD and SV_FOP_S/D with a literal
register; fp_op_s/d and fp_fma_s/d with literal registers (simd_vloc.h makes them macros over the value forms). A
function that calls a helper reading V registers itself (sl_*, sv_* below) or uses one of the forms with a register
that is not a literal keeps the Cpu: nothing here guesses.
"""
import os
import re

# helpers that take register numbers and read or write V registers inside (runtime/cpu/simd.h). Those in HELPERS work on
# V (simd_vloc.h maps them to their _r form); given literal register arguments, regs() names what they touch. A
# function calling any other one keeps the Cpu.
def _rng(t, k):
    return [(t + i) & 31 for i in range(k)]


HELPERS = {   # name -> the registers of its arguments (a: the arguments after c, as ints where literal)
    'sv_fred_s': lambda a: [a[1], a[2]],
    'sl_lds': lambda a: _rng(a[3], a[1]),                                # t .. t+selem-1
    'sl_sts': lambda a: _rng(a[3], a[1]),
    'sl_ldr': lambda a: _rng(a[3], a[2]),
}
CPU_ONLY = re.compile(r'\b(?!(?:' + '|'.join(HELPERS) + r')\()(?:sl_\w+|sv_\w+)\(c\b')
HELPER_CALL = re.compile(r'\b(' + '|'.join(HELPERS) + r')\(c,')


def _args(text, i):
    """The top-level arguments of the call whose '(' is at text[i], as ints where literal, else None."""
    depth, cur, out = 0, '', []
    for ch in text[i + 1:]:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            if depth == 0:
                out.append(cur)
                break
            depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur)
            cur = ''
        elif not (ch == ')' and depth == 0):
            cur += ch
    vals = []
    for x in out[1:]:   # after c
        x = x.strip()
        try:
            vals.append(int(x, 0))
        except ValueError:
            vals.append(None)
    return vals


def helper_regs(text):
    """V registers the HELPERS calls in text touch, or None when one has a register argument that is not literal."""
    out = set()
    for m in HELPER_CALL.finditer(text):
        a = _args(text, m.end(1))
        try:
            regs = HELPERS[m.group(1)]([x if x is not None else 0 for x in a])
            need = HELPER_ARGS[m.group(1)]
        except IndexError:
            return None
        if any(a[k] is None for k in need):
            return None
        out.update(regs)
    return out


HELPER_ARGS = {   # the argument positions HELPERS reads registers or counts from: they must be literal
    'sl_gen': (3, 7, 10), 'sl_across': (4, 5), 'sv_fred_s': (1, 2), 'sv_tbl': (1, 3, 4, 5),
    'sl_ldm': (2, 3, 4), 'sl_stm': (2, 3, 4), 'sl_lds': (1, 3), 'sl_sts': (1, 3), 'sl_ldr': (2, 3),
}
FORMS = {   # name -> the pattern of its literal-register occurrences (each group a register)
    'VREG': r'\bVREG\(\s*[^,()]+,\s*(\d+)\s*\)',
    'VQ': r'\bVQ\(\s*[^,()]+,\s*[^,()]+,\s*(\d+)\s*\)',
    'VW': r'\bVW\(\s*[^,()]+,\s*[^,()]+,\s*(\d+)\s*,',
    'VS8': r'\bVS8\((\d+)\)', 'VS16': r'\bVS16\((\d+)\)', 'VS32': r'\bVS32\((\d+)\)', 'VS64': r'\bVS64\((\d+)\)',
    'VSF32': r'\bVSF32\((\d+)\)', 'VSF64': r'\bVSF64\((\d+)\)', 'VHI64': r'\bVHI64\((\d+)\)',
    'FP_SETS': r'\bFP_SETS\((\d+),', 'FP_SETD': r'\bFP_SETD\((\d+),',
    'SV_FOP_S': r'\bSV_FOP_S\(\s*[^,()]+,\s*[^,()]+,\s*(\d+),',
    'SV_FOP_D': r'\bSV_FOP_D\(\s*[^,()]+,\s*[^,()]+,\s*(\d+),',
    'fp_op_s': r'\bfp_op_s\(c,\s*[^,()]+,\s*(\d+),\s*(\d+),\s*(\d+)\)',
    'fp_op_d': r'\bfp_op_d\(c,\s*[^,()]+,\s*(\d+),\s*(\d+),\s*(\d+)\)',
    'fp_fma_s': r'\bfp_fma_s\(c,\s*\d+,\s*\d+,\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)',
    'fp_fma_d': r'\bfp_fma_d\(c,\s*\d+,\s*\d+,\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)',
}
FORM_RE = {k: re.compile(v) for k, v in FORMS.items()}
NAME_RE = {k: re.compile(r'\b' + k + r'\(') for k in FORMS}
DIRECT = re.compile(r'c->v\[(\d+)\]')
ANY_CV = re.compile(r'c->v\b')


def refs(text):
    """The V registers text names, or None when it has a form this module does not follow."""
    if CPU_ONLY.search(text):
        return None
    out = {int(m) for m in DIRECT.findall(text)}
    h = helper_regs(text)
    if h is None:
        return None
    out |= h
    if len(ANY_CV.findall(text)) != len(DIRECT.findall(text)):
        return None
    for k, rx in FORM_RE.items():
        if k not in text:
            continue
        found = rx.findall(text)
        if len(found) != len(NAME_RE[k].findall(text)):
            return None
        for g in found:
            out.update(int(x) for x in (g if isinstance(g, tuple) else (g,)))
    return out


class VPlan:
    def __init__(self, regs, spill):
        self.regs = regs     # sorted V registers the function keeps in V[]
        self.spill = spill   # per instruction: registers to store at its sync points
        self.reload = ''.join(f' VX({r}) = c->v[{r}];' for r in regs)

    def decl(self):
        # float lanes: the scalar FP code that dominates reads lane 0 as float and writes whole vectors, which clang's
        # SROA then keeps in XMM registers; a u128 array went to general register pairs and the stack
        return 'vf32 V[32];' + ''.join(f' VX({r}) = c->v[{r}];' for r in self.regs)

    def spill_text(self, i):
        return ''.join(f'c->v[{r}] = VX({r}); ' for r in sorted(self.spill[i]))


def plan(texts, succ, clean, spill_marker):
    """A VPlan for the function (texts[i]: instruction i's C with regs.py's markers), or None when it keeps the Cpu:
    a form refs() does not follow, or no V register at all. Touched registers count as written (a store of a register
    that only was read is harmless, as in regs.py)."""
    n = len(texts)
    touched = []
    for t in texts:
        r = refs(t)
        if r is None:
            return None
        touched.append(r)
    regs = set().union(*touched) if touched else set()
    if not regs:
        return None
    dirty = [set() for _ in range(n)]
    seen = [False] * n
    work = [0] if n else []
    if n:
        seen[0] = True
    while work:
        i = work.pop()
        out = set() if i in clean else dirty[i] | touched[i]
        for s in succ[i]:
            if not seen[s] or not out <= dirty[s]:
                seen[s] = True
                dirty[s] |= out
                work.append(s)
    for i in range(n):
        if not seen[i]:
            dirty[i] = set(regs)
    return VPlan(sorted(regs), [dirty[i] | touched[i] if spill_marker in texts[i] else set() for i in range(n)])


# Locals pay off only where calls are rare. x86-64 SysV has no callee-saved vector register, so around each call clang
# keeps the live locals on the stack as well as syncing them with the Cpu. Static x86 of 191 functions of 7 hot chunks
# (17/11/2026), all V in the Cpu against locals, by calls per V access in the emitted body: below 0.01 -24 % instructions
# and -45 % memory operands, 0.010-0.015 -10 % / -22 %, 0.015-0.02 +11 % / +5 %, 0.02-0.03 +29 % / +35 %.
CALL_DENSITY = float(os.environ.get('MKW_GEN_V_CALL_DENSITY', '0.015'))
CALL_RE = re.compile(r'\b(?:f_[0-9a-f]+|rt_dispatch)\(c\);')
VREF_RE = re.compile(r'\bVX\(|\bVREG\(|\bVS\w*\(|\bFP_SET\w\(|\bfp_op_\w\(|\bfp_fma_\w\(|\bVQ\(|\bVW\(|\bSV_FOP|\bsl_\w+\(|\bsv_\w+\(')


def worth(decl, lines):
    """Whether a function with V locals (its declaration and emitted lines) has calls rare enough for them to pay."""
    text = decl + '\n'.join(lines)
    return len(CALL_RE.findall(text)) <= CALL_DENSITY * max(1, len(VREF_RE.findall(text)))
