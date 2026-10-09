# 环境搭建踩坑记录

> 记录一切「装了半天才搞通」的东西。目的：重装系统时不重复踩坑。

## 机器信息

- 系统：Windows
- GPU：RTX 5060 Laptop 8GB（Blackwell 架构）
- CPU：AMD R9 8940H

---

## 待记录项

### 1. WSL2

- 安装命令：
- 遇到的问题：
- 解决办法：

### 2. CUDA 12.8 + PyTorch 2.7/cu128

> Blackwell 架构**必须** CUDA 12.8+ / PyTorch 2.7+。装旧版会报
> `no kernel image is available for execution on the device`

- 验证命令：`python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"`
- 遇到的问题：
- 解决办法：

### 3. Ollama + Qwen3

- 安装命令：
- Qwen3-4B（Q4 约 2.5GB）实测：
- Qwen3-8B（Q4 约 5.5GB）实测：
- 遇到的问题：

### 4. API 平台

- DeepSeek：
- 通义百炼：
- 智谱 GLM：
