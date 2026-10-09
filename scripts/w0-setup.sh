#!/usr/bin/env bash
# ============================================================
# W0 环境一键搭建（WSL2 / Ubuntu 24.04 / RTX 5060 Blackwell）
# ------------------------------------------------------------
# 用法（在 WSL 的 Ubuntu 里）：
#     bash /mnt/d/code/ai-playground/scripts/w0-setup.sh
#
# 设计前提（本机实测）：
#   - 代理工具为 TUN + fake-ip 模式，GitHub 不通，国内镜像飞快
#   - 因此全程避开 GitHub，改用国内镜像源
#   - 直接用系统自带 Python 建 venv，不需要 uv 去 GitHub 下 Python
#   - 不硬编码 Python 版本，脚本对 Ubuntu 24.04 / 26.04 均适用
#
# 幂等：重复运行是安全的
# ============================================================
set -euo pipefail

VENV_DIR="$HOME/.venvs/torch"
APT_SRC="/etc/apt/sources.list.d/ubuntu.sources"
TUNA="https://mirrors.tuna.tsinghua.edu.cn"
SJTU_TORCH="https://mirror.sjtu.edu.cn/pytorch-wheels/cu128"

step() { echo ""; echo "====> $*"; echo ""; }

# ------------------------------------------------------------
step "[1/5] 切换 apt 源为清华镜像（Ubuntu 24.04 是 deb822 格式）"
# ------------------------------------------------------------
if [ ! -f "$APT_SRC" ]; then
  echo "!! 找不到 $APT_SRC，请确认发行版是 Ubuntu 24.04"
  exit 1
fi
[ -f "$APT_SRC.bak" ] || sudo cp "$APT_SRC" "$APT_SRC.bak"
sudo sed -i \
  -e "s|http://archive.ubuntu.com|$TUNA|g" \
  -e "s|http://security.ubuntu.com|$TUNA|g" \
  -e "s|http://cn.archive.ubuntu.com|$TUNA|g" \
  "$APT_SRC"
echo "--- 当前源 ---"
grep -E '^URIs' "$APT_SRC" || true

# ------------------------------------------------------------
step "[2/5] 更新索引并安装基础工具"
# ------------------------------------------------------------
sudo apt update
# python3-venv 是版本无关的元包，会拉到当前系统对应的 python3.X-venv
sudo apt install -y \
  build-essential git curl wget unzip ca-certificates \
  python3-venv python3-pip

# ------------------------------------------------------------
step "[3/5] 安装 uv"
# ------------------------------------------------------------
export PATH="$HOME/.local/bin:$PATH"
if command -v uv >/dev/null 2>&1; then
  echo "uv 已存在，跳过"
else
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv --version

# ------------------------------------------------------------
step "[4/5] 创建虚拟环境（用系统自带 Python，避开 GitHub）"
# ------------------------------------------------------------
SYS_PY=/usr/bin/python3
echo "系统 Python：$("$SYS_PY" --version 2>&1)"
if [ -x "$VENV_DIR/bin/python" ]; then
  echo "虚拟环境已存在：$VENV_DIR"
else
  uv venv "$VENV_DIR" --python "$SYS_PY"
fi

# ------------------------------------------------------------
step "[5/5] 安装 PyTorch cu128（Blackwell sm_120 必须 cu128+）"
# ------------------------------------------------------------
# 主源：上海交大镜像（本机实测 0.15s）
# 备选：https://download.pytorch.org/whl/cu128
# 两者均已确认提供 cp314 (Python 3.14) 的 linux x86_64 wheel
if ! uv pip install --python "$VENV_DIR/bin/python" torch --index-url "$SJTU_TORCH"; then
  echo ""
  echo "!! 上交大镜像安装失败，回退到 PyTorch 官方源 ..."
  uv pip install --python "$VENV_DIR/bin/python" torch \
    --index-url "https://download.pytorch.org/whl/cu128"
fi

# ------------------------------------------------------------
step "GPU 验收"
# ------------------------------------------------------------
"$VENV_DIR/bin/python" - <<'PY'
import torch

print("torch      :", torch.__version__)
print("cuda(rt)   :", torch.version.cuda)
print("available  :", torch.cuda.is_available())

ok = True
if not torch.cuda.is_available():
    ok = False
    print("!! CUDA 不可用 —— 可能装成了 CPU 版，或 wheel 与 GPU 架构不匹配")
else:
    print("device     :", torch.cuda.get_device_name(0))
    cap = torch.cuda.get_device_capability(0)
    print("capability :", cap, "(期望 (12, 0) = Blackwell)")
    if cap != (12, 0):
        ok = False
        print("!! 计算能力不是 sm_120")
    x = torch.randn(4096, 4096, device="cuda")
    y = x @ x
    torch.cuda.synchronize()
    s = float(y.sum())
    print("matmul sum :", s)
    if s != s:  # NaN 检测
        ok = False
        print("!! 矩阵乘法结果异常")

print("")
print("==== W0 环境验收：" + ("通过 ✅" if ok else "未通过 ❌") + " ====")
PY

echo ""
echo "下一步："
echo "  source $VENV_DIR/bin/activate"
echo "  python ~/gpu_check.py"
