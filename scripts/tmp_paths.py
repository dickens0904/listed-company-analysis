"""
统一临时文件管理器 - 业务侧便捷引用入口
====================================

封装manager.py的常用接口，自动处理sys.path，避免业务代码硬编码tmp目录。
"""
import importlib.util
import sys
from pathlib import Path

_TMP_DIR = Path(__file__).resolve().parent.parent.parent.parent / 'tmp'
_MANAGER_PY = _TMP_DIR / 'manager.py'


def _load_manager():
    """加载宿主 tmp/manager.py；找不到时回退到 skill 本地缓存目录，保证 import 永不崩溃。

    2026-10-22 打包审计修复：原实现在 manager.py 缺失时直接 raise ImportError，
    导致打包到其他机器后 peer_discovery（from tmp_paths import PDF_CACHE_DIR）直接崩。
    """
    if _MANAGER_PY.exists():
        _spec = importlib.util.spec_from_file_location("tmp_manager", _MANAGER_PY)
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules['tmp_manager'] = _mod
            _spec.loader.exec_module(_mod)
            return _mod

    # ── 兜底：未找到宿主 manager.py（如打包到其他机器）──
    _skill_root = Path(__file__).resolve().parent.parent
    _local = _skill_root / '.tmp'

    class _FallbackManager:
        WORKSPACE_ROOT = _skill_root
        TMP_ROOT = _local
        PDF_CACHE_DIR = _local / 'pdf'
        RUNTIME_DIR = _local / 'runtime'
        ARCHIVE_DIR = _local / 'archive'
        MIAOXIANG_DIR = _local / 'miaoxiang'
        RUNTIME_CHARTS = _local / 'charts'
        RUNTIME_LOGS = _local / 'logs'
        RUNTIME_TEXT = _local / 'text'
        DEFAULT_RETENTION_DAYS = 7

        def ensure_tmp_dirs(self):
            for _d in (self.PDF_CACHE_DIR, self.RUNTIME_DIR, self.ARCHIVE_DIR,
                       self.MIAOXIANG_DIR, self.RUNTIME_CHARTS, self.RUNTIME_LOGS,
                       self.RUNTIME_TEXT):
                _d.mkdir(parents=True, exist_ok=True)

        def get_tmp_root(self):
            return self.TMP_ROOT

        def get_runtime_dir(self):
            return self.RUNTIME_DIR

        def get_miaoxiang_dir(self):
            return self.MIAOXIANG_DIR

        def cleanup_expired_files(self, *a, **k):
            return 0

        def get_tmp_usage(self):
            return "fallback(local .tmp)"

        def format_size(self, n):
            return f"{n}B"

    _fb = _FallbackManager()
    _fb.ensure_tmp_dirs()
    return _fb


_manager = _load_manager()

# 透传 manager 的所有接口
WORKSPACE_ROOT = _manager.WORKSPACE_ROOT
TMP_ROOT = _manager.TMP_ROOT
PDF_CACHE_DIR = _manager.PDF_CACHE_DIR
RUNTIME_DIR = _manager.RUNTIME_DIR
ARCHIVE_DIR = _manager.ARCHIVE_DIR
MIAOXIANG_DIR = _manager.MIAOXIANG_DIR
RUNTIME_CHARTS = _manager.RUNTIME_CHARTS
RUNTIME_LOGS = _manager.RUNTIME_LOGS
RUNTIME_TEXT = _manager.RUNTIME_TEXT
DEFAULT_RETENTION_DAYS = _manager.DEFAULT_RETENTION_DAYS

ensure_tmp_dirs = _manager.ensure_tmp_dirs
get_tmp_root = _manager.get_tmp_root
get_runtime_dir = _manager.get_runtime_dir


# ============================================================
# PDF 缓存接口 · 兼容适配层（2026-10-19 修复 API 双重漂移）
# ============================================================
# 现象：`announcements.fetch_announcements(deep_extract=True)` 对**全部 1354 条**
#   公告的 `extracted_content` 全部填入同一个错误：
#       "get_cached_pdf_path() takes 1 positional argument but 2 were given"
#   → 公告全文抽取 100% 失效 → 三幕叙事时间线只剩标题、没有灵魂。
#
# 根因：`manager.py` 是**扁平命名空间** API
#       get_cached_pdf_path(name)                → PDF_CACHE_DIR / name
#       get_pdf_cache_path(name)                 → PDF_CACHE_DIR / name
#       save_to_pdf_cache(name, content: bytes)  → 写字节流
#   而业务代码（announcements.py / prospectus.py，共 4 处调用）按**旧的两参数
#   路径版**在用：get_cached_pdf_path(stock_code, art_code) 等。
#   —— 典型的"底层库换版本、上层未同步"。
#
# 修法：在这一层做**签名自适应**，不逐个改 4 处调用点（避免再漂移）。
#       新版(1 参) 与旧版(2 参/3 参) 都支持，且缓存文件名规则统一。
# ============================================================

def _pdf_cache_name(stock_code: str, art_code: str, ext: str = 'pdf') -> str:
    """统一的 PDF 缓存文件名：{stock}_{art_code}.{ext}（扁平、可读、可跨会话复用）"""
    return f"{stock_code}_{art_code}.{ext}"


def get_cached_pdf_path(stock_code: str, art_code: str = None, *args, **kwargs):
    """兼容 get_cached_pdf_path(name) / get_cached_pdf_path(stock, art_code)

    Returns:
        Path（可能不存在——调用方须自行 exists() 判断）
    """
    name = _pdf_cache_name(stock_code, art_code) if art_code else stock_code
    return PDF_CACHE_DIR / name


def get_pdf_cache_path(stock_code: str, art_code: str = None, ext: str = 'pdf', *a, **kw):
    """兼容 get_pdf_cache_path(name) / get_pdf_cache_path(stock, art_code, ext)"""
    if art_code:
        name = _pdf_cache_name(stock_code, art_code, ext or 'pdf')
    else:
        name = stock_code if str(stock_code).endswith('.pdf') else f"{stock_code}.{ext or 'pdf'}"
    return PDF_CACHE_DIR / name


def save_to_pdf_cache(*args, **kwargs):
    """兼容 save_to_pdf_cache(name, content: bytes) / save_to_pdf_cache(path, stock, art)

    旧版语义是"把磁盘文件存进缓存"，新版是"把字节流写进缓存"。
    这里按参数个数与类型自动分流：
        (path, stock, art)  → 读磁盘文件写缓存
        (name, bytes)       → 直接写
    """
    if len(args) >= 3:                      # 旧版：save_to_pdf_cache(pdf_path, stock, art)
        src, stock_code, art_code = args[0], args[1], args[2]
        name = _pdf_cache_name(stock_code, art_code)
        p = PDF_CACHE_DIR / name
        if p.exists():
            return p                        # 已缓存，不重复写
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_bytes(Path(src).read_bytes())
            return p
        except Exception:
            from scripts.silenced_errors import record_result
            record_result(__name__, 'save_to_pdf_cache', Exception('写入缓存失败'),
                          result={}, note=f'src={src}')
            return None
    # 新版：(name, content)
    name = args[0] if args else kwargs.get('name')
    content = args[1] if len(args) > 1 else kwargs.get('content', b'')
    p = PDF_CACHE_DIR / str(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else str(content).encode('utf-8'))
    return p


get_miaoxiang_dir = _manager.get_miaoxiang_dir
cleanup_expired_files = _manager.cleanup_expired_files
get_tmp_usage = _manager.get_tmp_usage
format_size = _manager.format_size


def get_output_dir(stock_code: str, run_date: str = None):
    """获取本次分析的 output 目录（位于 skills/listed-company-analysis/output）"""
    from datetime import datetime
    lca_root = WORKSPACE_ROOT / 'skills' / 'listed-company-analysis'
    output_root = lca_root / 'output'
    if run_date is None:
        run_date = datetime.now().strftime('%Y%m%d')
    run_dir = output_root / f"{stock_code}_{run_date}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


__all__ = [
    'WORKSPACE_ROOT', 'TMP_ROOT', 'PDF_CACHE_DIR', 'RUNTIME_DIR', 'ARCHIVE_DIR',
    'MIAOXIANG_DIR', 'RUNTIME_CHARTS', 'RUNTIME_LOGS', 'RUNTIME_TEXT',
    'DEFAULT_RETENTION_DAYS', 'ensure_tmp_dirs', 'get_tmp_root',
    'get_runtime_dir', 'get_pdf_cache_path', 'get_cached_pdf_path',
    'save_to_pdf_cache', 'get_miaoxiang_dir', 'cleanup_expired_files',
    'get_tmp_usage', 'format_size', 'get_output_dir',
]
