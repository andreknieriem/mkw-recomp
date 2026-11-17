// The V register macros for the generated code (recomp/vregs.py), included after simd.h by every chunk: they index V,
// which each generated function declares, as a local array synced with c->v at calls (functions vregs.py follows) or
// as a pointer to c->v (every other function: the code as it was). The inline helpers of simd.h were defined before
// this header and keep c->v; vregs.py keeps the Cpu in every function that calls one of those that read V registers
// themselves (sl_*, sv_*). fp_op_* and fp_fma_* become their value forms here, so that they read V too.
#pragma once
#include "simd.h"

#undef VREG
#undef VQ
#undef VW
#undef VS8
#undef VS16
#undef VS32
#undef VS64
#undef VSF32
#undef VSF64
#undef VHI64
#undef FP_SETS
#undef FP_SETD
// VX(n): the whole register as a u128 lvalue, whatever V's element type (the lifted c->v[n] in a local function)
#define VX(n) (*(u128 *)&V[n])
#define VREG(T, n) (*(T *)&V[n])
#define VQ(T, Q, n) ((T)((Q) ? VX(n) : (u128)(uint64_t)VX(n)))
#define VW(T, Q, d, e) do { T _w = (e); VX(d) = (Q) ? (u128)_w : (u128)(uint64_t)(u128)_w; } while (0)
#define VS8(n) (*(uint8_t *)&V[n])
#define VS16(n) (*(sa16 *)&V[n])
#define VS32(n) (*(sa32 *)&V[n])
#define VS64(n) (*(sa64 *)&V[n])
#define VSF32(n) (*(saf32 *)&V[n])
#define VSF64(n) (*(saf64 *)&V[n])
#define VHI64(n) (((sa64 *)&V[n])[1])
// a scalar result in lane 0 and zeros above, as simd.h's (c->v[d] = fb_s(x)): the same bits, written as a vector so
// that a local V register stays in a vector register (an i128 store makes clang keep it in two general registers)
#define FP_SETS(d, x) (VREG(vf32, d) = (vf32){(x), 0, 0, 0})
#define FP_SETD(d, x) (VREG(vf64, d) = (vf64){(x), 0})
// simd.h fp_op_s/d and fp_fma_s/d, as expressions over the macros above (same operand order)
#define fp_op_s(c, op, d, n, m) ((void)FP_SETS(d, op_s(c, op, VSF32(n), VSF32(m), 0)))
#define fp_op_d(c, op, d, n, m) ((void)FP_SETD(d, op_d(c, op, VSF64(n), VSF64(m), 0)))
#define fp_fma_s(c, na, nn, d, n, m, a) \
    ((void)FP_SETS(d, op_s(c, FOP_MADD, (na) ? neg_s(VSF32(a)) : VSF32(a), (nn) ? neg_s(VSF32(n)) : VSF32(n), VSF32(m))))
#define fp_fma_d(c, na, nn, d, n, m, a) \
    ((void)FP_SETD(d, op_d(c, FOP_MADD, (na) ? neg_d(VSF64(a)) : VSF64(a), (nn) ? neg_d(VSF64(n)) : VSF64(n), VSF64(m))))
// sl_* / sv_* helpers that index V registers by number: on V, the local array or c->v (recomp/vregs.py HELPERS)
#undef sl_gen
#define sl_gen(c, ...) sl_gen_r(c, (u128 *)V, __VA_ARGS__)
#undef sl_across
#define sl_across(c, ...) sl_across_r(c, (u128 *)V, __VA_ARGS__)
#undef sv_fred_s
#define sv_fred_s(c, ...) sv_fred_s_r(c, (u128 *)V, __VA_ARGS__)
#undef sv_tbl
#define sv_tbl(c, ...) sv_tbl_r(c, (u128 *)V, __VA_ARGS__)
#undef sl_ldm
#define sl_ldm(c, ...) sl_ldm_r(c, (u128 *)V, __VA_ARGS__)
#undef sl_stm
#define sl_stm(c, ...) sl_stm_r(c, (u128 *)V, __VA_ARGS__)
#undef sl_lds
#define sl_lds(c, ...) sl_lds_r(c, (u128 *)V, __VA_ARGS__)
#undef sl_sts
#define sl_sts(c, ...) sl_sts_r(c, (u128 *)V, __VA_ARGS__)
#undef sl_ldr
#define sl_ldr(c, ...) sl_ldr_r(c, (u128 *)V, __VA_ARGS__)
