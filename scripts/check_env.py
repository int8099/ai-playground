"""
环境自检 —— 确认 PyCharm 用的是不是正确的解释器
================================================================

【为什么需要这个脚本】
    这个项目用虚拟环境（.venv）隔离依赖。但 PyCharm 里可能配了好几个
    解释器，一不小心就跑到别的环境上去了，报出莫名其妙的
    「No module named 'xxx'」。

    这个脚本【只用标准库】写 —— 所以即使用错了解释器它也能跑起来，
    然后告诉你：你在哪个环境里、缺什么、该怎么修。

【怎么跑】
    PyCharm：右键本文件 → Run 'check_env'
    命令行：  python scripts/check_env.py

    在 Python Console 里也可以：  exec(open('scripts/check_env.py').read())
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# ══════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# 这个项目需要的关键依赖：(import 名, pip 包名)
REQUIRED = [
    ("httpx", "httpx"),
    ("pydantic", "pydantic"),
    ("pydantic_settings", "pydantic-settings"),
    ("dotenv", "python-dotenv"),
    ("llmkit", "ai-playground（本项目，editable 安装）"),
]


def banner(title: str) -> None:
    print(f"\n{'═' * 64}\n  {title}\n{'═' * 64}")


def get_version(module_name: str, pip_name: str) -> str | None:
    """检查包是否可用并拿到版本号。不可用返回 None。

    分两步，因为 import 名和 pip 包名【经常不一样】：
        import dotenv          ←  pip 包名是 python-dotenv
        import llmkit          ←  pip 包名是 ai-playground

    第 1 步用 find_spec 看到底能不能 import（这才是真正影响运行的事）；
    第 2 步用 metadata 按 pip 包名查版本号。
    """
    # 第 1 步：能不能 import —— 这才是我们真正关心的
    try:
        if importlib.util.find_spec(module_name) is None:
            return None
    except (ImportError, ValueError):
        return None

    # 第 2 步：查版本号。查不到也不算失败，包反正在。
    try:
        import importlib.metadata as md

        return md.version(pip_name)
    except Exception:
        return "已安装"


def main() -> int:
    banner("环境自检")

    exe = Path(sys.executable).resolve()
    print(f"  解释器路径 : {exe}")
    print(f"  Python 版本: {sys.version.split()[0]}")
    print(f"  sys.prefix : {sys.prefix}")
    print(f"  sys.base_prefix: {sys.base_prefix}")

    expected = EXPECTED_PYTHON.resolve() if EXPECTED_PYTHON.exists() else EXPECTED_PYTHON

    # ── 判定 ──────────────────────────────────────────────────
    print()
    in_venv = sys.prefix != sys.base_prefix
    if exe == expected:
        print("  判定       : ✅ 正确 —— 这正是项目的虚拟环境 (.venv)")
        verdict_ok = True
    elif in_venv:
        print("  判定       : ⚠️  在某个虚拟环境里，但不是本项目的那一个")
        print(f"               应该是: {expected}")
        verdict_ok = False
    else:
        print("  判定       : ❌ 错误 —— 这是【系统 Python】，不是项目环境")
        print(f"               应该是: {expected}")
        verdict_ok = False

    # ── 依赖检查 ──────────────────────────────────────────────
    print(f"\n{'─' * 64}")
    print("  依赖检查\n")
    missing: list[str] = []
    for mod, pip_name in REQUIRED:
        ver = get_version(mod, pip_name)
        if ver is None:
            missing.append(pip_name)
            print(f"    ❌ {mod:<20} 缺失")
        else:
            print(f"    ✅ {mod:<20} {ver}")

    # ── 结论 ──────────────────────────────────────────────────
    print()
    if verdict_ok and not missing:
        banner("✅ 一切正常")
        print("""
  解释器正确、依赖齐全，可以放心跑其它脚本：

      scripts/llmkit_demo.py                    端到端演示（会真实调用 API）
      experiments/w1-05-httpx/01_raw_call.py    httpx 基础
      experiments/w1-05-httpx/02_timeout_errors.py
      experiments/w1-05-httpx/03_streaming.py
      experiments/w1-05-httpx/04_thinking_control.py
""")
        return 0

    banner("❌ 环境不对")

    if not verdict_ok:
        print(f"""
  问题：PyCharm 用的解释器不是本项目的 .venv
        你现在的：{exe}
        应该是  ：{expected}

  为什么会这样：
        PyCharm 里存着【不止一个】解释器。这个项目里至少有两个名字：

            uv (ai-playground)            → D:\\code\\ai-playground\\.venv\\Scripts\\python.exe   ✅ 对的
            Python 3.13 (ai-playground)   → D:\\Python312\\python.exe                          ❌ 系统 Python

        注意第二个名字很坑 —— 它叫 "ai-playground"，但实际指向【系统 Python】。
        项目级配置用的是第一个，模块级和运行配置却用了第二个，
        所以你会跑到系统 Python 上去。

  【修复：三选一，推荐第一个】

    ▸ 方法 1（最快，10 秒）
        看 PyCharm 窗口【右下角状态栏】，那里显示着当前解释器的名字。
        点它 → 在弹出的列表里选 uv (ai-playground)

    ▸ 方法 2（更直观）
        Ctrl+Alt+S  →  左侧选中 Project: ai-playground  →  Python Interpreter
        →  右上角下拉框里选 uv (ai-playground)
        →  确认右侧包列表里能看到 httpx 和 pydantic
        →  OK

    ▸ 方法 3（前两个都找不到时）
        Ctrl+Alt+S  →  Python Interpreter  →  Add Interpreter
        →  Add Local Interpreter...  →  左侧 Virtualenv Environment  →  Existing
        →  Interpreter 填：
               {expected}
        →  OK  →  OK

  改完之后：重新右键运行这个脚本，应该显示「✅ 一切正常」。
""")

    if missing:
        print(f"  另外还缺依赖：{', '.join(missing)}")
        print("""
        正常情况下，只要解释器指向 .venv，这些包本来就都在 ——
        因为它们是靠 uv 装进 .venv 的。

        如果解释器已经改对、却仍然缺包，在项目根目录执行：

            uv pip install --python ".venv/Scripts/python.exe" httpx pydantic pydantic-settings python-dotenv
            uv pip install --python ".venv/Scripts/python.exe" -e .

        ⚠️ 本项目【没有】requirements.txt —— 依赖清单在 pyproject.toml 里，
           由 uv 管理。别去 pip install -r，那个文件不存在。
""")

    banner("为什么不用别的方式修")
    print("""
  你可能想：直接改 .idea 下的配置文件不就完了？
  现在不行 —— PyCharm 正在运行，它用的是内存里的配置，
  并且退出时会把内存里的旧配置写回文件，覆盖掉外部的修改。

  所以这类问题只在 PyCharm 界面里改，或者先完全退出 PyCharm
  再改配置文件。
""")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
