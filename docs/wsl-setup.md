# WSL2 + PyTorch cu128 环境搭建 Runbook

> 本机显卡：**RTX 5060 Laptop 8GB（Blackwell，sm_120）**
> 本机 Windows 驱动：**592.01**（支持 CUDA 13.1，满足 Blackwell 的 570+ 要求）
> 本机发行版：**Ubuntu 26.04.1 LTS**，系统 Python **3.14.4**
> 目标：在 WSL2/Ubuntu 里跑通 `torch.cuda.is_available() == True`

## 已验证的 wheel 可用性（避免版本试错）

| 源 | cu128 + cp314 (Python 3.14) + linux x86_64 |
|---|---|
| PyTorch 官方 `download.pytorch.org/whl/cu128` | ✅ 2.9.0 / 2.9.1 / 2.10.0 / **2.11.0** |
| 上交大镜像 `mirror.sjtu.edu.cn/pytorch-wheels/cu128` | ✅ 同上 |

> 查法：`curl -s https://download.pytorch.org/whl/cu128/torch/ | grep -oE 'cp3[0-9]+' | sort -u`
> 装机前先查一遍，能省一轮「装完才发现没有对应 wheel」的返工。

---

## 0. 核心认知（先看这条，能省 2 小时）

**WSL2 里不需要单独安装 CUDA Toolkit。**

pip 装的 `torch` wheel **自带 CUDA runtime**（约 2.5GB 的体积主要就是这个）。
WSL 通过微软的 `/usr/lib/wsl/lib/libcuda.so` 直接调用 **Windows 侧驱动**。

所以要装的东西只有两样：
1. Windows 侧：NVIDIA 驱动（只需一个，且**不要**在 WSL 里重装 Linux 版驱动）
2. WSL 侧：`torch` 的 cu128 wheel

**反面教材**：在 WSL 里跑去 NVIDIA 官网下 `.run` 装 Linux 驱动 / 装 CUDA Toolkit，会把 `/usr/lib/wsl/lib` 覆盖坏，导致 GPU 直接失效。别干这事。

---

## 1. 验收 WSL 与发行版

在 **Windows PowerShell** 里：

```powershell
wsl -l -v
```

期望输出（`VERSION` 必须是 **2**，`STATE` 为 Running 或 Stopped 都行）：

```
  NAME      STATE           VERSION
* Ubuntu    Stopped         2
```

- 若 `VERSION` 是 **1** → 立刻转换（WSL1 没有 GPU 透传，必定失败）：
  ```powershell
  wsl --set-version Ubuntu 2
  ```
- 若提示「没有已安装的分发」→ 回到安装步骤。

---

## 2. 进 Ubuntu 做 GPU 通透体检

```powershell
wsl -d Ubuntu
```

进去后依次执行：

```bash
# 2.1 内核版本（应含 microsoft-standard-WSL2）
uname -r

# 2.2 GPU 透传设备节点（存在 = 透传通了）
ls -l /dev/dxg

# 2.3 最关键的一步：WSL 里能直接看到 Windows 的 nvidia-smi
nvidia-smi
```

验收标准：
- `/dev/dxg` **存在**
- `nvidia-smi` 能列出 `NVIDIA GeForce RTX 5060 ...`，且 Driver Version 显示 `592.01`

> 若 `nvidia-smi` 提示 command not found：检查 `/usr/lib/wsl/lib/nvidia-smi` 是否存在。
> 若 `/dev/dxg` 不存在：说明发行版还是 WSL1，回第 1 步转换。

---

## 3. 换国内源 + 装基础工具

Ubuntu 24.04 用的是 deb822 格式的源文件（路径是 `ubuntu.sources`，**不是** `sources.list`）。

```bash
# 备份
sudo cp /etc/apt/sources.list.d/ubuntu.sources /etc/apt/sources.list.d/ubuntu.sources.bak

# 换清华源
sudo sed -i 's|http://archive.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g; s|http://security.ubuntu.com|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/ubuntu.sources

# 更新 + 装工具
sudo apt update && sudo apt upgrade -y
sudo apt install -y build-essential git curl wget unzip ca-certificates \
  python3-venv python3-pip
```

> `python3-venv` 是版本无关的元包，别写 `python3.12-venv` 这类带版本号的
> —— 发行版一升级就会报 `Unable to locate package`。

> 如果 `apt update` 报 `Could not resolve mirrors.tuna.tsinghua.edu.cn`，是 DNS 问题：
> `sudo sh -c 'echo "nameserver 223.5.5.5" > /etc/resolv.conf'`

---

## 4. 装 uv（Python 环境与依赖管理）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

> 若 `astral.sh` 下不动（国内偶发），降级方案：
> `pip install uv`（需先 `sudo apt install -y python3-pip`）

---

## 5. 装 PyTorch cu128

**必须显式指定 cu128 索引**：PyPI 默认 wheel 的 CUDA 版本对 sm_120 不保证，跑起来会报
`no kernel image is available for execution on the device`。

```bash
# 5.1 建虚拟环境（直接用系统自带 Python，不要用 uv python install）
#     ⚠️ uv python install 要访问 GitHub，国内环境必挂
SYS_PY=/usr/bin/python3
"$SYS_PY" --version
uv venv ~/.venvs/torch --python "$SYS_PY"
source ~/.venvs/torch/bin/activate

# 5.2 装 torch（约 2.5GB，慢慢下）
uv pip install torch --index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu128

# 5.3 补充常用库
uv pip install numpy matplotlib jupyter -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**国内加速备选**（若上交大镜像缺某个版本）：

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/cu128
```

---

## 6. GPU 验证（W0 的验收关卡）

把下面存成 `~/gpu_check.py`：

```python
import torch

print("torch     :", torch.__version__)
print("cuda(runtime):", torch.version.cuda)
print("available :", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device    :", torch.cuda.get_device_name(0))
    print("capability:", torch.cuda.get_device_capability(0))  # 期望 (12, 0)

    x = torch.randn(4096, 4096, device="cuda")
    y = x @ x
    torch.cuda.synchronize()
    print("matmulsum :", y.sum().item())
```

运行：

```bash
python ~/gpu_check.py
```

**验收标准（四条全中才算 W0 环境过关）：**
1. `available : True`
2. `capability: (12, 0)` ← Blackwell 的标志
3. `matmulsum` 打印出一个正常数字（不是 nan / inf）
4. 全程**没有** `no kernel image is available` 警告

---

## 7. 报错对照表

| 现象 | 原因 | 解决 |
|---|---|---|
| `torch.cuda.is_available()` 返回 False | 用了 CPU 版 wheel | 重装，加 `--index-url .../cu128` |
| `no kernel image is available for execution on the device` | wheel 的 CUDA 太旧，不认 sm_120 | 换 cu128/cu129 wheel |
| `nvidia-smi` 在 WSL 里找不到设备 | 发行版是 WSL1 | `wsl --set-version Ubuntu 2` |
| `/dev/dxg` 不存在 | 驱动太旧 或 装过 Linux 版驱动 | 更新 Windows 驱动；清掉 WSL 内的 Linux 驱动 |
| `apt` 卡在 `archive.ubuntu.com` | 默认源在国外 | 换清华源（第 3 步） |
| `Unable to locate package python3.12-venv` | 硬编码了 Python 版本号，与发行版不匹配 | 改用版本无关的 `python3-venv` 元包 |
| `uv python install` 卡死 / 超时 | 它要从 github.com 下载独立 Python | 改用系统自带 Python 建 venv（第 5 步） |
| WSL 里显存显示不对 / 独占 | WSL2 显存由 Windows 统一管理，属正常 | 无视，看 `torch.cuda.mem_get_info()` |

---

## 8. 与本仓库其他文档的关系

- 踩坑流水账记在 `docs/env-notes.md`
- AI 给出的错误建议记在 `docs/ai-correction-log.md`
- 本文件是**可复制的操作手册**，只保留「照着敲就能通」的部分
