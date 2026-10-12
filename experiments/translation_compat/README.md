# Hy-MT2 30B GGUF 兼容性诊断

独立的只读 GGUF tensor descriptor 检查与 llama.cpp 小范围补丁。不改模型权重，
不自动加载模型，不启动推理。实际运行产物位于忽略目录
`.local/translation-evaluation/20261006-v1/hy30-compat/`。

## 已确认的加载问题

指定 GrahLnn revision `4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9` 的
Hy-MT2-30B-A3B Q3_K_M 包含 766 个 tensor，其中第 1–47 层各有
`blk.<层>.exp_probs_b.bias`，形状为 `[128]`。它们是 MoE expert 选择偏置。
本机 b11429 对应源码 `d81235049384534c167caea52b85a694f6103d14` 使用没有
`.bias` 后缀的名称请求该项，导致 47 个 tensor 未被使用，正好解释
`expected 766, got 719`。这次失败发生在 tensor 加载阶段，并非显存不足的证据。

[固定模型发布者补丁](https://huggingface.co/GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF/blob/4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9/patches/llama-cpp-hyv3.patch)
创建此项时明确指定 `bias` 后缀。
[精确 b11429 loader](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/models/hy-v3.cpp)
以及最初上游 HYV3 支持使用无后缀名称；不能靠任意换一个上游版本解决此文件的命名差异。

`hy-v3-router-bias.patch` 保持上游名称优先；仅当该 tensor 不存在时，尝试发布者的
`.bias` 名称。它不删除、忽略或置零偏置，不改变量化或其他 tensor。原模型仍保留
原始 SHA256；自定义 runtime 必须独立记身份，不能冒称未修改的官方 b11429。

## 只读检查

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m experiments.translation_compat.inspect_gguf `
  '.local/models/translation/hy-mt2-30b-a3b-q3-k-m/Hy-MT2-30B-A3B-Q3_K_M.gguf' `
  --output '.local/translation-evaluation/<run-id>/hy30-descriptors.json'
```

检查器只读取 metadata 与 descriptor，不读取 tensor 数据区，也不修改文件。
结果保留各 tensor 的名称、形状、类型与原始 offset，可核对兼容映射是否覆盖全部
原始 tensor。输出采用独占创建，已有文件不能覆盖。

## 引擎修复与验证边界

在原生 Windows 上使用现有 VS2019 BuildTools 构建精确 b11429 的 `llama` 共享库，
仅在其 `src/models/hy-v3.cpp` 应用上述 fallback。编译不需要 CUDA toolkit，
因为只构建 loader／图构建的 core；独立 runtime 复制官方 CUDA 13.4 release
全部组件，再只替换 `llama.dll`，继续使用原始 `ggml-cuda.dll`。
此路径需按实际产物核对 DLL 依赖、导出与哈希，并由外层完成 GPU 加载和推理验证。
CPU 编译不代表推理回退 CPU；设备驻留须以实际服务器日志为准。

本目录的静态诊断和编译不能代替模型 smoke。加载成功后仍需检查全部原始 tensor、
实际 GPU 驻留、模板、停止条件与日中翻译输出。具体验证状态以 runtime 清单与
本轮报告为准，不从本 README 推定已完成模型评估。

本轮已构建 core，并使用 `no_alloc.cpp` 实测原始 GGUF 的 766 个 descriptor 完整加载，
分配为 0 MiB。另以两份小型合成零权重 GGUF 验证：上游无后缀名称与发布者 `.bias`
名称均能加载全部 19 个 tensor。检查器只显式加载 CPU metadata backend，设置
`no_alloc=true`、`load_mode=none`，不执行任何模型推理；这不是 CPU 翻译回退。
这项证据不等同 CUDA 实际推理验收。

`package_runtime.py` 将官方 runtime 复制到全新目录，只替换 `llama.dll`，核对其他 DLL
逐字节未变，生成显式 `identity.json`：源码 commit、archive／补丁／core 哈希、构建参数、
编译器与所有 runtime DLL 身份。可通过外层运行器的 `--engine` 与 `--engine-identity`
选择这份实验 runtime；原始官方目录保留。

离线基础测试：

```powershell
& '.venv/Scripts/python.exe' -X utf8 -m unittest experiments.translation_compat.test_compat -v
```

设置 `LLAMA_NO_ALLOC_CHECKER` 与 `LLAMA_NO_ALLOC_CPU_BACKEND` 为上述检查器和
其 CPU metadata DLL 的绝对路径后，同一测试会增加两份合成文件的真实 loader 检查。
未设置时只检查只读 parser／descriptor，不假称 native 验证已运行。

## 原生包装逐字节核验

`verify_templates.py` 在现有 Jinja2 环境中执行 GGUF 内嵌真实模板，用单个 user
消息、`add_generation_prompt=true` 核对当前 Adapter。Hy30 显式使用
`reasoning_effort=no_think`。本轮合成源文检查中，Hy7／Hy30／Tower+ 三个实际
生成 prompt 与 Jinja 输出逐字节一致；不加载模型，不调用推理。

额外首尾空白诊断显示 Tower+ 的 Jinja 会 `trim user.content`，当前 `wrap` helper
原样保留空白；实际 `render` 任务没有首尾空白，因此上述实测 prompt 一致。此差异
明确保留，未暗中修改 renderer。复用 helper 输入任意首尾空白时应留意该边界。

```powershell
& '.local/envs/whisper-latest/Scripts/python.exe' -X utf8 `
  -m experiments.translation_compat.verify_templates `
  --output '.local/translation-evaluation/<run-id>/template-validation-other.json'
```

输出保存 Jinja 版本／环境、实际模板与 Adapter 哈希、完整合成消息、渲染结果及比较。
TranslateGemma 的语言字段与原生模板由对应独立核验记录覆盖。
