//! Experimental ranking kernel only. Not a runtime dependency.
//! Caller owns all buffers; no allocations, I/O, strings or financial writes.
#![no_std]

use core::panic::PanicInfo;
#[panic_handler]
fn panic(_: &PanicInfo) -> ! { loop {} }

/// Inputs are caller-validated equally sized arrays. Select maximum score,
/// then earliest canonical ISO start (as YYYYMMDD), then lexical ID rank.
/// Count all score ties, regardless of secondary deterministic ordering.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn choose_trip(
    scores: *const i64, starts: *const u64, ids: *const u64,
    count: usize, out_index: *mut usize, out_ties: *mut usize,
) -> i32 {
    if count == 0 || scores.is_null() || starts.is_null() || ids.is_null()
        || out_index.is_null() || out_ties.is_null() { return -1; }
    let mut best = 0usize;
    let mut ties = 1usize;
    let mut i = 1usize;
    while i < count {
        let s = unsafe { *scores.add(i) };
        let current = unsafe { *scores.add(best) };
        if s > current {
            best = i;
            ties = 1;
        } else if s == current {
            ties += 1;
            let start = unsafe { *starts.add(i) };
            let best_start = unsafe { *starts.add(best) };
            if start < best_start || (start == best_start
                && unsafe { *ids.add(i) < *ids.add(best) }) { best = i; }
        }
        i += 1;
    }
    unsafe { *out_index = best; *out_ties = ties; }
    0
}
