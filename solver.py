import math
import time
import heapq
import sys
import bisect
import os
import subprocess
from array import array
from typing import List, Dict, Any, Tuple, Optional, Iterable

try:
    import psutil  # type: ignore
except Exception:
    psutil = None


# ----------------------------- DEFAULT CONFIG -----------------------------

DEFAULT_CONFIG: Dict[str, Any] = {
    'N': 1,
    'consts': {},

    # === 函數開關 ===
    'use_sin': 0,
    'use_cos': 0,
    'use_tan': 0,
    'use_exp': 0,
    'use_ln': 0,
    'use_sqrt': 0,
    'use_neg': 0,
    'use_pow': 0,

    # === 策略設定 ===
    'generation_depth': 27,
    'keep_top': 1,
    'max_seconds': 12000.0,

    'dedup_precision': 10,
    'epsilon': 1e-12,

    # 單核版保留這個欄位只是為了相容舊設定，實際不使用
    'cpu_count': 1,
    'verbose': 1,

    # === 記憶體控制 ===
    # 0 或 <=0 表示不限制。若目前總 RSS 超過此值，會提早結束階段 1 並進入階段 2。
    'memory_limit_mb': 8000,
    # 每處理多少個 batch 檢查一次記憶體，避免每個 batch 都查造成額外開銷。
    'memory_check_every_batches': 16,
    # 單核版不會有 children，但保留欄位避免外部 config 壞掉。
    'memory_include_children': 0,
}


# ----------------------------- Op Codes -----------------------------

OP_VAL = 0
OP_ADD = 1
OP_SUB = 2
OP_MUL = 3
OP_DIV = 4
OP_POW = 5
OP_SIN = 6
OP_COS = 7
OP_TAN = 8
OP_EXP = 9
OP_LN = 10
OP_SQRT = 11
OP_NEG = 12

OP_CODE = {
    '+': OP_ADD,
    '-': OP_SUB,
    '*': OP_MUL,
    '/': OP_DIV,
    '^': OP_POW,
    'sin': OP_SIN,
    'cos': OP_COS,
    'tan': OP_TAN,
    'exp': OP_EXP,
    'ln': OP_LN,
    'sqrt': OP_SQRT,
    'neg': OP_NEG,
}

OP_STR = {
    OP_ADD: '+',
    OP_SUB: '-',
    OP_MUL: '*',
    OP_DIV: '/',
    OP_POW: '^',
    OP_SIN: 'sin',
    OP_COS: 'cos',
    OP_TAN: 'tan',
    OP_EXP: 'exp',
    OP_LN: 'ln',
    OP_SQRT: 'sqrt',
    OP_NEG: '-',
}

UNARY_NAME_TO_CODE = {
    'sin': OP_SIN,
    'cos': OP_COS,
    'tan': OP_TAN,
    'exp': OP_EXP,
    'ln': OP_LN,
    'sqrt': OP_SQRT,
    '-': OP_NEG,
}


# ----------------------------- Worker -----------------------------

def safe_math(func, v):
    try:
        res = func(v)
        if math.isfinite(res):
            return res
    except Exception:
        pass
    return None


def worker_task(args):
    """
    單核版仍保留這個函式，作為單個 task 的執行器。
    回傳格式：[(val, op_name, left_id, right_id), ...]
    單元運算的 right_id 固定為 -1。
    """
    task_type = args[0]

    local_new_items = []
    local_seen = set()
    _isfinite = math.isfinite
    _round = round
    _abs = abs

    def try_add(val, op_name, left_id, right_id):
        k = _round(val, precision)
        if k not in local_seen:
            local_seen.add(k)
            local_new_items.append((val, op_name, left_id, right_id))

    if task_type == 'unary':
        _, src_vals, src_ids, u_keys, precision, epsilon = args
        EPS = epsilon
        funcs = []
        if 'sin' in u_keys:
            funcs.append(('sin', math.sin))
        if 'cos' in u_keys:
            funcs.append(('cos', math.cos))
        if 'tan' in u_keys:
            funcs.append(('tan', math.tan))
        if 'exp' in u_keys:
            funcs.append(('exp', math.exp))
        if 'ln' in u_keys:
            funcs.append(('ln', math.log))
        if 'sqrt' in u_keys:
            funcs.append(('sqrt', math.sqrt))
        if '-' in u_keys:
            funcs.append(('-', lambda x: -x))

        for idx in range(len(src_vals)):
            v = src_vals[idx]
            node_id = src_ids[idx]
            for name, f in funcs:
                if name == 'ln' and v <= EPS:
                    continue
                if name == 'sqrt' and v < -EPS:
                    continue
                val = safe_math(f, v)
                if val is not None:
                    try_add(val, name, node_id, -1)

    elif task_type == 'binary':
        _, vals_a, ids_a, vals_b, ids_b, ops, precision, epsilon = args
        EPS = epsilon
        do_add = '+' in ops
        do_sub = '-' in ops
        do_mul = '*' in ops
        do_div = '/' in ops
        do_pow = '^' in ops

        len_a = len(vals_a)
        len_b = len(vals_b)

        for i in range(len_a):
            lv = vals_a[i]
            lid = ids_a[i]
            for j in range(len_b):
                rv = vals_b[j]
                rid = ids_b[j]

                if do_add and lv >= rv:
                    val = lv + rv
                    if _isfinite(val):
                        try_add(val, '+', lid, rid)

                if do_sub:
                    val = lv - rv
                    if _isfinite(val):
                        try_add(val, '-', lid, rid)

                if do_mul and lv >= rv:
                    val = lv * rv
                    if _isfinite(val):
                        try_add(val, '*', lid, rid)

                if do_div:
                    if _abs(rv) > EPS:
                        val = lv / rv
                        if _isfinite(val):
                            try_add(val, '/', lid, rid)
                    if _abs(lv) > EPS:
                        val = rv / lv
                        if _isfinite(val):
                            try_add(val, '/', rid, lid)

                if do_pow:
                    try:
                        val = math.pow(lv, rv)
                        if _isfinite(val):
                            try_add(val, '^', lid, rid)
                    except Exception:
                        pass
                    try:
                        val = math.pow(rv, lv)
                        if _isfinite(val):
                            try_add(val, '^', rid, lid)
                    except Exception:
                        pass

    return local_new_items


# ----------------------------- Helpers -----------------------------

def merge_config(base: Dict[str, Any], overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not overrides:
        return dict(base)
    cfg = dict(base)
    cfg.update(overrides)
    return cfg


def bytes_to_mb(num_bytes: int) -> float:
    return num_bytes / (1024.0 * 1024.0)


def get_process_rss_bytes(pid: int) -> int:
    """盡量跨平台取得目前 RSS，單位 bytes；失敗時回傳 0。"""
    if pid <= 0:
        return 0

    # 1) psutil 最穩，支援 Linux / macOS / Windows。
    if psutil is not None:
        try:
            return int(psutil.Process(pid).memory_info().rss)
        except Exception:
            pass

    # 2) Linux: /proc/<pid>/status 或 /proc/<pid>/statm
    if sys.platform.startswith('linux'):
        status_path = f'/proc/{pid}/status'
        try:
            with open(status_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1]) * 1024
        except Exception:
            pass

        statm_path = f'/proc/{pid}/statm'
        try:
            with open(statm_path, 'r', encoding='utf-8', errors='ignore') as f:
                parts = f.read().strip().split()
                if len(parts) >= 2:
                    rss_pages = int(parts[1])
                    page_size = os.sysconf('SC_PAGE_SIZE')
                    return rss_pages * page_size
        except Exception:
            pass

    # 3) Windows: ctypes + GetProcessMemoryInfo
    if os.name == 'nt':
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ('cb', wintypes.DWORD),
                    ('PageFaultCount', wintypes.DWORD),
                    ('PeakWorkingSetSize', ctypes.c_size_t),
                    ('WorkingSetSize', ctypes.c_size_t),
                    ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                    ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                    ('PagefileUsage', ctypes.c_size_t),
                    ('PeakPagefileUsage', ctypes.c_size_t),
                ]

            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010

            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            psapi = ctypes.WinDLL('psapi', use_last_error=True)

            OpenProcess = kernel32.OpenProcess
            OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            OpenProcess.restype = wintypes.HANDLE

            CloseHandle = kernel32.CloseHandle
            CloseHandle.argtypes = [wintypes.HANDLE]
            CloseHandle.restype = wintypes.BOOL

            GetProcessMemoryInfo = psapi.GetProcessMemoryInfo
            GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]
            GetProcessMemoryInfo.restype = wintypes.BOOL

            hproc = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
            if hproc:
                try:
                    counters = PROCESS_MEMORY_COUNTERS()
                    counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
                    ok = GetProcessMemoryInfo(hproc, ctypes.byref(counters), counters.cb)
                    if ok:
                        return int(counters.WorkingSetSize)
                finally:
                    CloseHandle(hproc)
        except Exception:
            pass

    # 4) macOS / 其他 Unix: 用 ps 指令查 RSS (KB)
    try:
        out = subprocess.check_output(
            ['ps', '-o', 'rss=', '-p', str(pid)],
            stderr=subprocess.DEVNULL,
            text=True
        )
        rss_kb = out.strip()
        if rss_kb:
            return int(rss_kb) * 1024
    except Exception:
        pass

    return 0


def get_total_rss_bytes(include_children: bool = False) -> int:
    """
    單核版只回傳主程序 RSS。
    include_children 參數保留只是為了相容舊呼叫方式。
    """
    _ = include_children
    return get_process_rss_bytes(os.getpid())


def iter_tasks_for_cost(
    cost: int,
    layers_vals: List[array],
    layers_ids: List[array],
    u_keys: List[str],
    b_keys: List[str],
    precision: int,
    eps: float,
    cpu_count: int,
) -> Iterable[Tuple[Any, ...]]:
    if u_keys and len(layers_vals[cost - 1]) > 0:
        yield ('unary', layers_vals[cost - 1], layers_ids[cost - 1], u_keys, precision, eps)

    for a_cost in range(1, cost // 2 + 1):
        b_cost = cost - a_cost
        vals_a = layers_vals[a_cost]
        ids_a = layers_ids[a_cost]
        vals_b = layers_vals[b_cost]
        ids_b = layers_ids[b_cost]

        if len(vals_a) == 0 or len(vals_b) == 0:
            continue

        if len(vals_a) > len(vals_b):
            vals_a, vals_b = vals_b, vals_a
            ids_a, ids_b = ids_b, ids_a

        # 單核版仍保留分 batch，避免一次塞太大
        chunk_size = max(1000, len(vals_b) // max(1, cpu_count * 2))
        for j in range(0, len(vals_b), chunk_size):
            yield (
                'binary',
                vals_a,
                ids_a,
                vals_b[j:j + chunk_size],
                ids_b[j:j + chunk_size],
                b_keys,
                precision,
                eps,
            )


# ----------------------------- Main Solver -----------------------------

def solve(target: float, config_overrides: Optional[Dict[str, Any]] = None) -> Tuple[float, str]:
    cfg = merge_config(DEFAULT_CONFIG, config_overrides)

    N = int(cfg['N'])
    TARGET = float(target)
    GEN_DEPTH = int(cfg['generation_depth'])
    MAX_SEC = float(cfg['max_seconds'])
    PRECISION = int(cfg['dedup_precision'])
    KEEP_TOP = int(cfg['keep_top'])
    EPS = float(cfg['epsilon'])
    VERBOSE = bool(cfg.get('verbose', True))

    MEMORY_LIMIT_MB = float(cfg.get('memory_limit_mb', 0.0))
    MEMORY_LIMIT_BYTES = int(MEMORY_LIMIT_MB * 1024 * 1024) if MEMORY_LIMIT_MB > 0 else 0
    MEMORY_CHECK_EVERY = max(1, int(cfg.get('memory_check_every_batches', 16)))
    MEMORY_INCLUDE_CHILDREN = bool(cfg.get('memory_include_children', 0))

    unary_ops = []
    if cfg['use_sin']:
        unary_ops.append(('sin', math.sin, 'arcsin', math.asin, lambda x: -1 <= x <= 1))
    if cfg['use_cos']:
        unary_ops.append(('cos', math.cos, 'arccos', math.acos, lambda x: -1 <= x <= 1))
    if cfg['use_tan']:
        unary_ops.append(('tan', math.tan, 'arctan', math.atan, lambda x: True))
    if cfg['use_exp']:
        unary_ops.append(('exp', math.exp, 'ln', math.log, lambda x: x > EPS))
    if cfg['use_ln']:
        unary_ops.append(('ln', math.log, 'exp', math.exp, lambda x: x < 700))
    if cfg['use_sqrt']:
        unary_ops.append(('sqrt', math.sqrt, 'square', lambda x: x ** 2, lambda x: True))
    if cfg['use_neg']:
        unary_ops.append(('-', lambda x: -x, '-', lambda x: -x, lambda x: True))

    u_keys = [op[0] for op in unary_ops]
    b_keys = ['+', '-', '*', '/', '^'] if cfg['use_pow'] else ['+', '-', '*', '/']

    # Node store: 用平行陣列壓縮，避免大量 tuple / nested expr tree
    vals = array('d')
    costs = array('H')
    node_op = array('B')
    node_l = array('I')
    node_r = array('i')
    leaf_repr: Dict[int, str] = {}

    # 每層只保留值與節點 id；不保留 expr tree
    layers_vals: List[array] = [array('d') for _ in range(GEN_DEPTH + 1)]
    layers_ids: List[array] = [array('I') for _ in range(GEN_DEPTH + 1)]

    # rounded value -> node id
    global_map: Dict[float, int] = {}

    best_heap = []
    start_time = time.time()
    entry_counter = 0
    _abs = abs
    _round = round
    _heappush = heapq.heappush
    _heapreplace = heapq.heapreplace

    def update_best(val: float, ref_payload, cost: int) -> None:
        nonlocal entry_counter
        err = _abs(val - TARGET)
        if len(best_heap) < KEEP_TOP:
            entry_counter += 1
            _heappush(best_heap, (-err, entry_counter, val, ref_payload, cost))
        else:
            if err < -best_heap[0][0]:
                entry_counter += 1
                _heapreplace(best_heap, (-err, entry_counter, val, ref_payload, cost))

    def add_leaf(display_text: str, val: float) -> int:
        node_id = len(vals)
        vals.append(val)
        costs.append(1)
        node_op.append(OP_VAL)
        node_l.append(0)
        node_r.append(-1)
        leaf_repr[node_id] = str(display_text)
        global_map[_round(val, PRECISION)] = node_id
        update_best(val, ('node', node_id), 1)
        return node_id

    def add_generated(val: float, op_name: str, left_id: int, right_id: int,
                      cur_cost: int, new_ids: List[int], new_vals: List[float]) -> bool:
        k = _round(val, PRECISION)
        if k in global_map:
            return False

        node_id = len(vals)
        vals.append(val)
        costs.append(cur_cost)
        node_op.append(UNARY_NAME_TO_CODE[op_name] if right_id == -1 else OP_CODE[op_name])
        node_l.append(left_id)
        node_r.append(right_id)
        global_map[k] = node_id
        new_ids.append(node_id)
        new_vals.append(val)
        update_best(val, ('node', node_id), cur_cost)
        return True

    def node_to_str(node_id: int, memo: Dict[int, str]) -> str:
        cached = memo.get(node_id)
        if cached is not None:
            return cached

        op = node_op[node_id]
        if op == OP_VAL:
            res = leaf_repr[node_id]
        else:
            left_id = node_l[node_id]
            right_id = node_r[node_id]
            if right_id == -1:
                child = node_to_str(left_id, memo)
                if op == OP_NEG:
                    res = f"-({child})"
                else:
                    res = f"{OP_STR[op]}({child})"
            else:
                left = node_to_str(left_id, memo)
                right = node_to_str(right_id, memo)
                res = f"({left}{OP_STR[op]}{right})"

        memo[node_id] = res
        return res

    def ref_to_str(ref_payload) -> str:
        memo: Dict[int, str] = {}
        if ref_payload[0] == 'node':
            return node_to_str(ref_payload[1], memo)

        _, op_char, left_id, right_id, funcs = ref_payload
        res = f"({node_to_str(left_id, memo)}{op_char}{node_to_str(right_id, memo)})"
        for fname in reversed(funcs):
            if fname == '-':
                res = f"-({res})"
            else:
                res = f"{fname}({res})"
        return res

    def current_memory_bytes() -> int:
        return get_total_rss_bytes(include_children=MEMORY_INCLUDE_CHILDREN)

    if VERBOSE:
        print(f"Target: {TARGET}")
        print(f"階段 1: 單核生成 (Cost 1 ~ {GEN_DEPTH})")
        if MEMORY_LIMIT_BYTES > 0:
            print(f"記憶體門檻: {MEMORY_LIMIT_MB:.2f} MB (主程序)")

    # cost = 1 初始化
    cost1_ids: List[int] = []
    cost1_vals: List[float] = []
    for i in range(1, N + 1):
        node_id = add_leaf(str(i), float(i))
        cost1_ids.append(node_id)
        cost1_vals.append(float(i))

    for name, v in cfg['consts'].items():
        fv = float(v)
        k = _round(fv, PRECISION)
        if k not in global_map:
            node_id = add_leaf(str(name), fv)
            cost1_ids.append(node_id)
            cost1_vals.append(fv)

    layers_ids[1] = array('I', cost1_ids)
    layers_vals[1] = array('d', cost1_vals)

    stop_phase1 = False
    phase1_stop_reason = ''

    prev_layer_mem_bytes = current_memory_bytes()
    if VERBOSE:
        print(
            f"Layer  1 | 新增: {len(cost1_ids):7d} | 總庫存: {len(global_map):8d} | "
            f"RAM: {bytes_to_mb(prev_layer_mem_bytes):9.2f} MB | ΔRAM: {0.0:+8.2f} MB | 0.00s"
        )

    if MEMORY_LIMIT_BYTES > 0 and prev_layer_mem_bytes > MEMORY_LIMIT_BYTES:
        stop_phase1 = True
        phase1_stop_reason = (
            f"記憶體超過門檻 ({bytes_to_mb(prev_layer_mem_bytes):.2f} MB > {MEMORY_LIMIT_MB:.2f} MB)"
        )
        if VERBOSE:
            print(f"階段 1 提前結束：{phase1_stop_reason}")

    for cost in range(2, GEN_DEPTH + 1):
        if stop_phase1:
            break
        if time.time() - start_time > MAX_SEC:
            phase1_stop_reason = '時間到'
            break

        layer_start = time.time()
        new_ids: List[int] = []
        new_vals: List[float] = []
        new_count = 0
        batch_count = 0

        task_iter = iter_tasks_for_cost(
            cost, layers_vals, layers_ids, u_keys, b_keys, PRECISION, EPS, 1
        )

        for task in task_iter:
            batch_count += 1

            if time.time() - start_time > MAX_SEC:
                phase1_stop_reason = '時間到'
                stop_phase1 = True
                break

            batch_res = worker_task(task)

            for val, op_name, left_id, right_id in batch_res:
                if add_generated(val, op_name, left_id, right_id, cost, new_ids, new_vals):
                    new_count += 1

            if MEMORY_LIMIT_BYTES > 0 and (batch_count % MEMORY_CHECK_EVERY == 0):
                mem_now = current_memory_bytes()
                if mem_now > MEMORY_LIMIT_BYTES:
                    phase1_stop_reason = (
                        f"記憶體超過門檻 ({bytes_to_mb(mem_now):.2f} MB > {MEMORY_LIMIT_MB:.2f} MB)"
                    )
                    stop_phase1 = True
                    break

        layers_ids[cost] = array('I', new_ids)
        layers_vals[cost] = array('d', new_vals)

        dur = time.time() - layer_start
        cur_mem_bytes = current_memory_bytes()
        delta_mb = bytes_to_mb(cur_mem_bytes - prev_layer_mem_bytes)
        prev_layer_mem_bytes = cur_mem_bytes

        if VERBOSE:
            print(
                f"Layer {cost:2d} | 新增: {new_count:7d} | 總庫存: {len(global_map):8d} | "
                f"RAM: {bytes_to_mb(cur_mem_bytes):9.2f} MB | ΔRAM: {delta_mb:+8.2f} MB | {dur:.2f}s"
            )

        if (not stop_phase1) and MEMORY_LIMIT_BYTES > 0 and cur_mem_bytes > MEMORY_LIMIT_BYTES:
            stop_phase1 = True
            phase1_stop_reason = (
                f"記憶體超過門檻 ({bytes_to_mb(cur_mem_bytes):.2f} MB > {MEMORY_LIMIT_MB:.2f} MB)"
            )

        if stop_phase1:
            if VERBOSE:
                print(f"階段 1 提前結束：{phase1_stop_reason}")
            break

        if new_count == 0:
            phase1_stop_reason = '沒有新節點可生成'
            break

    # ---------------- MITM ----------------
    if VERBOSE:
        print("\n階段 2: MITM (使用二分搜尋進行模糊逼近)")

    mitm_targets: List[Tuple[float, Tuple[str, ...]]] = [(TARGET, tuple())]
    temp_targets: List[Tuple[float, Tuple[str, ...]]] = []

    for t_val, t_funcs in mitm_targets:
        for op_name, _, _, inv_func, domain_check in unary_ops:
            if domain_check(t_val):
                try:
                    inv_val = inv_func(t_val)
                    if math.isfinite(inv_val):
                        temp_targets.append((inv_val, t_funcs + (op_name,)))
                except Exception:
                    pass

    mitm_targets.extend(temp_targets)
    if VERBOSE:
        print(f"待查 Target 變體數量: {len(mitm_targets)}")
        print("正在排序數據以進行搜尋...")

    # MITM 不再需要逐層資料，先釋放
    del layers_vals
    del layers_ids

    all_node_ids = sorted(global_map.values(), key=vals.__getitem__)
    sorted_vals = array('d', (vals[node_id] for node_id in all_node_ids))

    if VERBOSE:
        print(f"排序完成。開始 MITM 掃描... (總數據量: {len(all_node_ids)})")
        print(f"進入階段 2 前 RAM: {bytes_to_mb(current_memory_bytes()):,.2f} MB")

    total_items = len(all_node_ids)

    def apply_outer_funcs(v: float, funcs: Tuple[str, ...]) -> Optional[float]:
        out = v
        for fname in reversed(funcs):
            try:
                if fname == 'sin':
                    out = math.sin(out)
                elif fname == 'cos':
                    out = math.cos(out)
                elif fname == 'tan':
                    out = math.tan(out)
                elif fname == 'exp':
                    out = math.exp(out)
                elif fname == 'ln':
                    out = math.log(out)
                elif fname == 'sqrt':
                    out = math.sqrt(out)
                elif fname == '-':
                    out = -out
                else:
                    return None
                if not math.isfinite(out):
                    return None
            except Exception:
                return None
        return out

    def check_nearest(needed_val: float, op_char: str, right_id: int, right_val: float,
                      funcs: Tuple[str, ...], is_reverse: bool = False):
        idx = bisect.bisect_left(sorted_vals, needed_val)
        candidate_positions = []
        if idx < len(all_node_ids):
            candidate_positions.append(idx)
        if idx > 0:
            candidate_positions.append(idx - 1)

        for pos in candidate_positions:
            left_id = all_node_ids[pos]
            left_val = vals[left_id]
            try:
                if not is_reverse:
                    if op_char == '+':
                        inner_val = left_val + right_val
                        final_left_id, final_right_id = left_id, right_id
                    elif op_char == '-':
                        inner_val = left_val - right_val
                        final_left_id, final_right_id = left_id, right_id
                    elif op_char == '*':
                        inner_val = left_val * right_val
                        final_left_id, final_right_id = left_id, right_id
                    elif op_char == '/':
                        if abs(right_val) <= EPS:
                            continue
                        inner_val = left_val / right_val
                        final_left_id, final_right_id = left_id, right_id
                    elif op_char == '^':
                        inner_val = math.pow(left_val, right_val)
                        final_left_id, final_right_id = left_id, right_id
                    else:
                        return
                else:
                    if op_char == '-':
                        inner_val = right_val - left_val
                        final_left_id, final_right_id = right_id, left_id
                    elif op_char == '/':
                        if abs(left_val) <= EPS:
                            continue
                        inner_val = right_val / left_val
                        final_left_id, final_right_id = right_id, left_id
                    elif op_char == '^':
                        inner_val = math.pow(right_val, left_val)
                        final_left_id, final_right_id = right_id, left_id
                    else:
                        return

                if not math.isfinite(inner_val):
                    continue

                final_val = apply_outer_funcs(inner_val, funcs)
                if final_val is None:
                    continue

                total_cost = int(costs[final_left_id]) + int(costs[final_right_id])
                update_best(
                    final_val,
                    ('compound', op_char, final_left_id, final_right_id, funcs),
                    total_cost,
                )
            except (ZeroDivisionError, ValueError, OverflowError):
                pass

    try:
        for i, right_id in enumerate(all_node_ids):
            if time.time() - start_time > MAX_SEC:
                if VERBOSE:
                    print('時間到，停止搜尋。')
                break

            if VERBOSE and (i % 5000 == 0):
                sys.stdout.write(f"\r進度: {i} / {total_items}")
                sys.stdout.flush()

            right_val = vals[right_id]
            for t_val, t_funcs in mitm_targets:
                check_nearest(t_val - right_val, '+', right_id, right_val, t_funcs)
                check_nearest(t_val + right_val, '-', right_id, right_val, t_funcs)
                check_nearest(right_val - t_val, '-', right_id, right_val, t_funcs, is_reverse=True)

                if abs(right_val) > EPS:
                    check_nearest(t_val / right_val, '*', right_id, right_val, t_funcs)
                    check_nearest(t_val * right_val, '/', right_id, right_val, t_funcs)

                if abs(t_val) > EPS:
                    check_nearest(right_val / t_val, '/', right_id, right_val, t_funcs, is_reverse=True)

                if cfg['use_pow']:
                    if abs(right_val) > EPS and t_val > 0:
                        try:
                            check_nearest(math.pow(t_val, 1 / right_val), '^', right_id, right_val, t_funcs)
                        except Exception:
                            pass

                    if t_val > 0 and right_val > 0:
                        try:
                            den = math.log(right_val)
                            if abs(den) > EPS:
                                check_nearest(
                                    math.log(t_val) / den,
                                    '^',
                                    right_id,
                                    right_val,
                                    t_funcs,
                                    is_reverse=True
                                )
                        except Exception:
                            pass

    except KeyboardInterrupt:
        pass
    except Exception as e:
        if VERBOSE:
            print(f"\nError: {e}")

    final_res = []
    while best_heap:
        neg_err, _, val, ref_payload, cost = heapq.heappop(best_heap)
        final_res.append((-neg_err, val, ref_payload, cost))

    final_res.sort(key=lambda x: x[0])
    best_err, best_val, best_ref, best_cost = final_res[0]
    best_expr_str = ref_to_str(best_ref)

    if VERBOSE:
        print("\n\n===== 搜尋結束 =====")
        print(f"Best err={best_err:.12g}, val={best_val}, cost={best_cost}")
        print(best_expr_str)

    return best_val, best_expr_str


# ----------------------------- Script mode example -----------------------------
if __name__ == '__main__':
    target = 1919810
    val, expr = solve(
        target,
        {
            # 'memory_limit_mb': 1024,
            # 'memory_check_every_batches': 8,
        }
    )

    print("\nReturned:")
    print("val =", val)
    print("expr =", expr)
    print("error=", abs(val - target) / target)
