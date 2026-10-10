#!/usr/bin/env bash
# ============================================================
# W0 环境体检脚本
# ------------------------------------------------------------
# 用法（在 WSL 的 Ubuntu 里）：
#     bash /mnt/d/code/ai-playground/scripts/w0-verify.sh
#
# 作用：把 W0 的每一项一次性验完，输出通过/失败清单。
#       环境出怪问题时先跑这个，能快速定位是哪一层坏了。
#       重装 WSL 后也可以跑它来确认装齐了没有。
# ============================================================

PROJ="/mnt/d/code/ai-playground"
VENV="$HOME/.venvs/torch"
PASS=0
FAIL=0
WARN=0

ok()   { printf '  \033[32m✅ %s\033[0m\n' "$1"; PASS=$((PASS+1)); }
bad()  { printf '  \033[31m❌ %s\033[0m\n' "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33m⚠️  %s\033[0m\n' "$1"; WARN=$((WARN+1)); }
sec()  { echo ""; printf '\033[1m=== %s ===\033[0m\n' "$1"; }

echo "############################################"
echo "#  W0 环境体检  $(date '+%Y-%m-%d %H:%M:%S')"
echo "############################################"

# ------------------------------------------------------------
sec "1. WSL 与 GPU 直通"
# ------------------------------------------------------------
KERNEL=$(uname -r)
case "$KERNEL" in
  *WSL2*) ok "WSL2 内核：$KERNEL" ;;
  *)      bad "当前不是 WSL2 内核：$KERNEL（WSL1 没有 GPU 直通）" ;;
esac

if [ -e /dev/dxg ]; then
  ok "/dev/dxg 存在（GPU 直通节点）"
else
  bad "/dev/dxg 不存在 —— GPU 直通未生效"
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  GPULINE=$(nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null | head -1)
  if [ -n "$GPULINE" ]; then
    ok "nvidia-smi 可用：$GPULINE"
  else
    bad "nvidia-smi 无输出 —— 驱动透传异常"
  fi
else
  bad "WSL 内找不到 nvidia-smi"
fi

# ------------------------------------------------------------
sec "2. Python 环境与 PyTorch"
# ------------------------------------------------------------
if [ -x "$VENV/bin/python" ]; then
  ok "虚拟环境存在：$VENV"
  "$VENV/bin/python" - <<'PY'
import sys
try:
    import torch
    print(f"  ✅ torch {torch.__version__} / runtime CUDA {torch.version.cuda}")
    if torch.cuda.is_available():
        print(f"  ✅ CUDA 可用：{torch.cuda.get_device_name(0)}")
        cap = torch.cuda.get_device_capability(0)
        if cap == (12, 0):
            print("  ✅ 计算能力 (12, 0) = Blackwell sm_120")
        else:
            print(f"  ⚠️  计算能力 {cap}，与预期的 (12, 0) 不符")
    else:
        print("  ❌ CUDA 不可用 —— 可能装了 CPU 版 wheel")
except ImportError as e:
    print(f"  ❌ 导入失败：{e}")
PY
else
  bad "虚拟环境不存在：$VENV（先跑 scripts/w0-setup.sh）"
fi

# 常用库
for m in numpy matplotlib jupyter; do
  if "$VENV/bin/python" -c "import $m" >/dev/null 2>&1; then
    ok "已安装：$m"
  else
    warn "未安装：$m  →  uv pip install $m -i https://pypi.tuna.tsinghua.edu.cn/simple"
  fi
done

# ------------------------------------------------------------
sec "3. Ollama 与本地推理"
# ------------------------------------------------------------
if command -v ollama >/dev/null 2>&1; then
  ok "ollama 已安装：$(ollama --version 2>&1 | head -1)"
else
  bad "ollama 未安装（跑 scripts/w0-ollama.sh）"
fi

VER=$(curl -s --max-time 5 http://127.0.0.1:11434/api/version 2>/dev/null)
if [ -n "$VER" ]; then
  ok "服务在运行：$VER"
else
  warn "服务未响应 →  nohup ollama serve > ~/.ollama/serve.log 2>&1 &"
fi

if command -v ollama >/dev/null 2>&1; then
  MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | tr '\n' ' ')
  if [ -n "$MODELS" ]; then
    ok "已下载模型：$MODELS"
  else
    warn "还没有模型 →  ollama pull --insecure qwen3:4b"
  fi
fi

# GPU 卸载情况
# 注意：ollama ps 的 PROCESSOR 列本身含空格（如 "100% GPU" 或 "48%/52% CPU/GPU"），
#       所以不能用固定列号取字段，要按整行内容匹配。
PS=$(ollama ps 2>/dev/null | tail -n +2)
if [ -n "$PS" ]; then
  if echo "$PS" | grep -q '100% GPU'; then
    ok "模型完全运行在 GPU 上（100% GPU）"
  elif echo "$PS" | grep -q 'GPU'; then
    warn "模型部分跑在 GPU，未达 100%：$(echo "$PS" | tail -1)"
  else
    warn "模型跑在 CPU 上：$(echo "$PS" | tail -1)"
  fi
else
  warn "当前没有已加载的模型（跑一次 ollama run 再看）"
fi

# ------------------------------------------------------------
sec "4. 项目配置"
# ------------------------------------------------------------
if [ -d "$PROJ/.git" ]; then
  ok "仓库存在：$PROJ"
  BRANCH=$(git -C "$PROJ" branch --show-current 2>/dev/null)
  ok "当前分支：$BRANCH"
else
  warn "未找到仓库：$PROJ"
fi

ENV_FILE="$PROJ/.env"
if [ -f "$ENV_FILE" ]; then
  ok ".env 存在"
  for k in DEEPSEEK_API_KEY DASHSCOPE_API_KEY ZHIPU_API_KEY; do
    v=$(grep -E "^${k}=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d ' \r')
    if [ ${#v} -ge 10 ]; then
      ok "$k 已填写（长度 ${#v}，不显示内容）"
    else
      warn "$k 未填写或过短（当前长度 ${#v}）"
    fi
  done
  # 确认没被 git 跟踪
  if git -C "$PROJ" check-ignore -q .env 2>/dev/null; then
    ok ".env 已被 .gitignore 忽略（不会被提交）"
  else
    bad ".env 未被忽略！有泄露风险"
  fi
else
  warn ".env 不存在（cp .env.example .env 后填 Key）"
fi

# ------------------------------------------------------------
sec "5. 磁盘空间"
# ------------------------------------------------------------
echo "--- 根文件系统 ---"
df -h / | sed '1d' | while read -r line; do echo "  $line"; done
AVAIL=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
if [ "${AVAIL:-0}" -ge 20 ]; then
  ok "根文件系统可用 ${AVAIL}G"
else
  warn "根文件系统仅剩 ${AVAIL}G，注意空间"
fi

# ------------------------------------------------------------
echo ""
echo "############################################"
printf '#  结果：通过 %d 项，警告 %d 项，失败 %d 项\n' "$PASS" "$WARN" "$FAIL"
echo "############################################"
if [ "$FAIL" -eq 0 ] && [ "$WARN" -eq 0 ]; then
  echo "🎉 W0 环境完全就绪。"
elif [ "$FAIL" -eq 0 ]; then
  echo "基本就绪，警告项按提示补齐即可。"
else
  echo "有失败项，按上面 ❌ 的提示处理。"
fi
