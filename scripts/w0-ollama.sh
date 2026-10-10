#!/usr/bin/env bash
# ============================================================
# W0 收尾：在 WSL 里安装 Ollama 并验证本地 GPU 推理
# ------------------------------------------------------------
# 用法（在 WSL 的 Ubuntu 里）：
#     bash /mnt/d/code/ai-playground/scripts/w0-ollama.sh
#     bash /mnt/d/code/ai-playground/scripts/w0-ollama.sh qwen3:8b   # 换模型
#
# 为什么要单独写这个脚本：
#   1. ollama.com/install.sh 会 307 跳转到 github.com，而本机 WSL 访问不了 GitHub
#   2. 官方安装脚本内部的资源文件名已从 .tgz 改为 .tar.zst，且需要 zstd 解压
#   3. 所以走 ghproxy.net 镜像手动拉包 + 手动解压，全程绕开 GitHub
#
# 实测链路（2026-10-10 核实）：
#   镜像 https://ghproxy.net/  → 206 Partial Content，可正常下载
#   资源 ollama-linux-amd64.tar.zst  → 1,436,368,794 B ≈ 1.34 GB
# ============================================================
set -euo pipefail

MODEL="${1:-qwen3:4b}"
VER="v0.40.2"
ASSET="ollama-linux-amd64.tar.zst"
GH="https://github.com/ollama/ollama/releases/download/${VER}/${ASSET}"

# ⚠️ 下载目录必须放在真实磁盘上。
# WSL 的 /tmp 是 tmpfs（内存盘，通常只有 3~4G），既放不下 1.34G 的包，
# 写进去还会占用内存。默认放 $HOME/.cache 下（在根文件系统上）。
WORK_DIR="${OLLAMA_DL_DIR:-$HOME/.cache/ollama-dl}"
mkdir -p "$WORK_DIR"
PKG="${WORK_DIR}/${ASSET}"

# 镜像列表（按实测速度排序，逐个尝试）
MIRRORS=(
  "https://ghproxy.net/${GH}"
  "https://ghfast.top/${GH}"
  "https://gh-proxy.com/${GH}"
)

step() { echo ""; echo "====> $*"; echo ""; }

# ------------------------------------------------------------
step "[1/5] 安装 zstd（解压 .tar.zst 必需）"
# ------------------------------------------------------------
if command -v zstd >/dev/null 2>&1; then
  echo "zstd 已安装：$(zstd --version)"
else
  sudo apt update -qq
  sudo apt install -y zstd
fi

# ------------------------------------------------------------
step "[2/5] 检查磁盘空间（1.34GB 安装包 + 约 2.5GB 模型 + 5GB 解压后）"
# ------------------------------------------------------------
echo "--- 下载目录所在文件系统 ---"
df -h "$WORK_DIR" | sed '1d'
echo "--- 根文件系统（解压目标 /usr/local）---"
df -h / | sed '1d'

# 分别检查：下载目录要 2G，根文件系统要 8G
check_space() {
  local path="$1" need="$2" label="$3"
  local avail
  avail=$(df -BG --output=avail "$path" | tail -1 | tr -dc '0-9')
  if [ "${avail:-0}" -lt "$need" ]; then
    echo "!! $label 可用空间不足：需要 ${need}G，当前 ${avail:-0}G（路径：$path）"
    return 1
  fi
  echo "OK  $label 可用 ${avail}G（需要 ${need}G）"
  return 0
}

check_space "$WORK_DIR" 2 "下载目录" || exit 1
check_space /          8 "根文件系统" || exit 1

# ------------------------------------------------------------
step "[3/5] 下载 Ollama 安装包（走镜像，绕开 GitHub）"
# ------------------------------------------------------------
if [ -f "$PKG" ] && [ "$(stat -c%s "$PKG")" -gt 1400000000 ]; then
  echo "安装包已存在且完整，跳过下载：$PKG"
else
  ok=0
  for m in "${MIRRORS[@]}"; do
    host=$(echo "$m" | cut -d/ -f3)
    echo "--- 尝试镜像：$host ---"
    # -C - 断点续传；重试 3 次
    if curl -L -C - --retry 3 --retry-delay 2 --connect-timeout 15 \
         --progress-bar -o "$PKG" "$m"; then
      sz=$(stat -c%s "$PKG" 2>/dev/null || echo 0)
      if [ "$sz" -gt 1400000000 ]; then
        echo "✅ 下载完成（$host）：$sz 字节"
        ok=1
        break
      else
        echo "⚠️  $host 下载不完整（$sz 字节），换下一个镜像"
      fi
    else
      echo "⚠️  $host 失败，换下一个镜像"
    fi
  done
  if [ "$ok" -eq 0 ]; then
    echo "!! 所有镜像均失败。手动兜底方案："
    echo "   ① 在 Windows 侧浏览器打开下面的地址下载（约 1.34GB）："
    echo "      https://ghproxy.net/${GH}"
    echo "   ② 把下载到的 ${ASSET} 放到 D:\\code\\ 下"
    echo "   ③ 回到 WSL 执行："
    echo "      zstd -d -c /mnt/d/code/${ASSET} | sudo tar -xf - -C /usr/local"
    echo "      ollama --version"
    exit 1
  fi
fi

# ------------------------------------------------------------
step "[4/5] 解压安装到 /usr/local"
# ------------------------------------------------------------
echo "解压中（约 5GB 解压后，需要一点时间）..."
zstd -d -c "$PKG" | sudo tar -xf - -C /usr/local
echo "--- 安装结果 ---"
ls -la /usr/local/bin/ollama 2>/dev/null || echo "!! 未找到 /usr/local/bin/ollama"
ollama --version

# ------------------------------------------------------------
step "[5/5] 启动服务并验证 GPU 推理"
# ------------------------------------------------------------
# WSL 里 systemd 通常没开，直接后台起服务最稳
if curl -s --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
  echo "Ollama 服务已在运行"
else
  echo "后台启动 ollama serve ..."
  mkdir -p "$HOME/.ollama"
  nohup ollama serve > "$HOME/.ollama/serve.log" 2>&1 &
  sleep 5
fi

echo "--- 服务状态 ---"
curl -s --max-time 5 http://127.0.0.1:11434/api/version || echo "!! 服务未响应，查看 $HOME/.ollama/serve.log"

echo ""
echo "--- 检测到的算力设备 ---"
# ollama 的日志会打印检测到的 GPU
grep -iE 'inference compute|library=cuda|no compatible GPUs|CPU' "$HOME/.ollama/serve.log" 2>/dev/null | tail -5 || echo "（日志暂无相关信息）"

echo ""
echo "--- 拉取模型：$MODEL（约 2.5GB，耐心等）---"
# 已知问题：本机代理用 fake-ip DNS，会把 R2 的 CDN 域名解析成 198.18.x.x，
# Ollama 有「拒绝连接非公网地址」的 SSRF 防护，于是报：
#   Error: redirect target not allowed: ...r2.cloudflarestorage.com resolves to non-public 198.18.0.37
# 解法：加 --insecure 跳过该重定向安全检查。
# 代价：本次拉取不做 TLS 证书校验（Ollama 仍会校验 blob 的 SHA256，损坏会失败）。
if ollama pull "$MODEL"; then
  :
else
  echo ""
  echo "!! 常规拉取失败，改用 --insecure 重试 ..."
  echo "   （原因：本地代理的 fake-ip DNS 触发 Ollama 的非公网地址防护）"
  ollama pull --insecure "$MODEL"
fi

echo ""
echo "--- 推理验证 ---"
ollama run "$MODEL" "用一句话说明你运行在什么设备上" --verbose

echo ""
echo "====> 完成。手动测试命令："
echo "    ollama run $MODEL \"你好\""
echo "    ollama ps              # 查看模型是否跑在 GPU 上"
echo ""
echo "注意：服务是 nohup 后台启动的，WSL 重启后需要重新执行"
echo "      （或临时执行：nohup ollama serve > ~/.ollama/serve.log 2>&1 &）"
