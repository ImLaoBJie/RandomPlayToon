"""Output paths must be explicit; never fall back to the process directory."""
import re
from pathlib import Path


def output_path(value, blend_filepath='', check_exists=True):
    raw = str(value).strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in '\"\'':
        raw = raw[1:-1]
    if not raw:
        raise ValueError('请填写输出完整路径，或点击“选择目录”。')
    if raw.startswith('//'):
        if not blend_filepath:
            raise ValueError('当前场景尚未保存，不能使用 // 相对路径；请选择完整输出路径。')
        path = Path(blend_filepath).parent / raw[2:]
    else:
        path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError('输出必须是完整路径，例如 E:/渲染结果/角色.blend；不能只填文件名或盘符相对路径。')
    if re.match(r'^[A-Za-z]__', path.name):
        raise ValueError('输出文件名疑似由整条路径改写而来（盘符后出现双下划线）。请将原始完整路径直接粘贴到面板，或重新选择目录。')
    if path.suffix.lower() != '.blend':
        raise ValueError('输出路径必须包含 .blend 文件名，例如 E:/渲染结果/角色.blend。')
    for component in path.parts[1:]:
        if any(ord(c) < 32 or c in '<>:"|?*' for c in component) or component.endswith((' ', '.')):
            raise ValueError('输出路径包含 Windows 不支持的字符、末尾空格或末尾句点。')
    path = path.resolve()
    if check_exists and (path.exists() or path.with_suffix('.report.json').exists()):
        raise ValueError('输出场景或报告已存在，请使用新路径。')
    if any(parent.exists() and not parent.is_dir() for parent in path.parents):
        raise ValueError('输出目录中的某一级是文件，请重新选择目录。')
    return path
