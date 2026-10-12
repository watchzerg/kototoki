# 四量化工程实验：精确身份附录

本附录摘录已验证的本地工程证据。权重完整 SHA256 沿用已冻结验证记录；完整权重身份沿用本轮冻结资产核验。首轮终评与四轮正式性能已完成，结果见正文；现基线身份保持 Q3_K_M。

## GGUF 文件与来源

| 候选 | 精确文件名 | 来源发布者／仓库 | 字节数 | 完整 SHA256 |
|---|---|---|---:|---|
| Q3_K_M（现基线） | `Hy-MT2-30B-A3B-Q3_K_M.gguf` | `GrahLnn/Hy-MT2-30B-A3B-4bit-GGUF` | 14446329888 | `9398dedb6f783963f0e9b7fc6ecb16a0158a92aa9a4c0a25eab29ba9704c19d5` |
| i1-Q3_K_M | `Hy-MT2-30B-A3B.i1-Q3_K_M.gguf` | `mradermacher/Hy-MT2-30B-A3B-i1-GGUF` | 14446330368 | `a70d7755b52cc96999c9d5645f881647c598967a5142b0177d7a6c018a4a3a46` |
| APEX-I-Compact | `Hy-MT2-30B-A3B-APEX-I-Compact.gguf` | `alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF` | 15035838080 | `8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a` |
| i1-Q3_K_L | `Hy-MT2-30B-A3B.i1-Q3_K_L.gguf` | `mradermacher/Hy-MT2-30B-A3B-i1-GGUF` | 15644000768 | `e63046e3379cc2cd43116146c42c2b433e8a6a7d86e85b13924f4a479c94395b` |

| 候选 | 冻结源 revision | 已验证时间（原记录） |
|---|---|---|
| Q3_K_M（现基线） | `4ae7787177f6d4f2d54ec2d543d9fe5f9114d1c9` | `2026-10-05T19:10:08.3356962Z` |
| i1-Q3_K_M | `c36beb0d9a93b2790313f6beff90482b492ce820` | `2026-10-06T13:00:21.0720745Z` |
| APEX-I-Compact | `312cce865e03a0718e36cfd1077e6307957aef72` | `2026-10-06T11:19:31.3919654Z` |
| i1-Q3_K_L | `c36beb0d9a93b2790313f6beff90482b492ce820` | `2026-10-06T12:11:33.5175771Z` |

来源发布者是 GGUF 仓库 owner；完整本地文件路径保存在本附录 JSON。

## 实际服务器与兼容修补身份

| 项目 | 精确记录 |
|---|---|
| 实际执行文件 | `D:\AI_Projects\kototoki\.local\translation-evaluation\20261006-v1\hy30-compat\runtime\llama-server.exe` |
| 执行文件字节数 | `9216` |
| 执行文件 SHA256 | `7e236243c9b670c6a49410c03186fd575c57a0efe3fd8a21d8727503d571d5b6` |
| 启动日志 build／版本标记 | `11429／b11429` |
| 完整 upstream commit | `d81235049384534c167caea52b85a694f6103d14` |
| 启动日志服务器编译器／目标 | `Clang 20.1.8／Windows x86_64` |
| 兼容运行时 identity | `llama-b11429-hyv3-router-bias-v1` |
| 修补 DLL 编译器 | `MSVC 19.29.30159.0 / VS2019 BuildTools 14.29.30133` |
| 修补 DLL CMake | `3.20.21032501-MSVC_2` |
| CUDA backend 来源记录 | `unchanged official b11429 CUDA13.4 ggml-cuda.dll` |
| 原始源包 SHA256 | `2c14039274aaf94ad0e4cbdeb575b32cc3d75c3b8bae28b052c9ff9c20ffea46` |
| 兼容补丁 SHA256 | `56d6b626187d2b5d2dc9edd8a130315b269191d76f9e5ee81a2fb800350ed330` |
| 修补后 HYV3 源文件 SHA256 | `c4e5d699a4d6b0e79da06313d2d841a37ee0fd840374e3c2669c2b4a5a1b0695` |

兼容修补只替换 `llama.dll`，用于 HYV3 router 偏置 tensor 的兼容命名，未修改或重命名模型权重。修补 DLL 的 MSVC 构建信息与现有服务器的 Clang 构建信息属于不同二进制。修补核心构建的 `GGML_CUDA=false` 不表示运行时未使用 CUDA；运行时保留原官方 CUDA backend。

`identity.json` 的 `custom-runtime-awaiting-gpu-smoke` 是构建时状态；其后四候选 validated-v3 审计全部通过，执行文件及完整 33 个 DLL 哈希与冻结记录一致，各记录均为 49/49 layers offloaded。逻辑 offload 记录不能单独证明所有数据持续驻留于独占物理显存。

| 关键 DLL | 完整 SHA256 |
|---|---|
| `llama.dll` | `f1e971f0557315afd71e7100c7efb9c56a36dc8aee68290908459d4cbc78ba86` |
| `llama-server-impl.dll` | `8bdf535224880cf5b919ada99e6cb225338cce4d444b8e5b4acd1e2bb10bc0a0` |
| `ggml-cuda.dll` | `ecf203f220cff5589119f39d8d4e9a2dcca8c47681187d5cf36363a8c29cd178` |
| `ggml-base.dll` | `19b7666b4cd7dc01e219e247783ffd1979694d6f1635bbf3209ae5fa0fc169c0` |
| `cudart64_13.dll` | `05bfafcb97bd53b0089568a96e1e5bd6921637bd0853ff7f5342bd31a6a16890` |
| `cublas64_13.dll` | `1119dbca0a808e0c8850bb4221e330daf0b5ddb348d62d37b6ac533854723df9` |
| `cublasLt64_13.dll` | `0f5bc315fef706b5626248ebd74e8a48a9e82fa2f0cad38330f5f70984913107` |

完整 33 个 DLL 身份清单保存在本附录 JSON 的 `engine.identity_record.runtime_dll_sha256`、工程 freeze.json 与 runtime/identity.json；各候选审计提供运行期间哈希一致性证据。

## 平台身份

| 项目 | 原记录 |
|---|---|
| 操作系统 | `Windows-11-10.0.26200-SP0` |
| CPU／逻辑线程 | `AMD Ryzen 7 5800X3D 8-Core Processor／16` |
| GPU | `NVIDIA GeForce RTX 5080` |
| GPU UUID | `GPU-aae9a94b-6362-eac8-6328-a2733d553dca` |
| NVIDIA driver | `617.14` |
| 监测报告总显存 | `16303.0 MiB` |
| GPU 身份观测时间 | `2026-10-06T16:19:25.317802+00:00` |

总显存沿用监测接口的原记录；不把不同接口的 memory total、used、free 相减后当成物理可用显存证明。

## 本地证据与完整哈希

| 证据绝对路径 | SHA256 |
|---|---|
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\engineering-freeze-v1\freeze.json` | `9778d116d664cf6589fbebde823b4b85550ed5985884143b1adb06d8ff306b27` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\20261006-v1\hy30-compat\runtime\identity.json` | `366f4d6b5e3facf52ba193b77d96632270f02e0384a89df805b6fceb6ac84755` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\20261006-v1\hy30-compat\runtime\llama-server.exe` | `7e236243c9b670c6a49410c03186fd575c57a0efe3fd8a21d8727503d571d5b6` |
| `D:\AI_Projects\kototoki\.local\manifests\translation-download-plan.json` | `f11ff6a74429b0454c7003a226bdc01ad240922986bfd473d3b7714b476a967c` |
| `D:\AI_Projects\kototoki\.local\manifests\hy30-shortlist-downloads.json` | `c4fff573d5d525014bbc625fbe2f6fd8f21c3c0521a3ba0229ebb2f1211672a3` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\stability-audit-v1\validated-v3\hy-mt2-30b-a3b-q3-k-m-audit.json` | `76c6e1d95420621a8a381984a05159eebf84ff6c07dc90dc48e22b5c4934e483` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\stability-audit-v1\validated-v3\hy-mt2-30b-a3b-i1-q3-k-m-audit.json` | `6aa84bb591ff1280f1c42a35ff60edab099690485e588d49c5a1655765a4c271` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\stability-audit-v1\validated-v3\hy-mt2-30b-a3b-apex-i-compact-audit.json` | `1f562bab91c9a41fd7335ad5706d194ccfd0bb051697f4d25a389cae62e91fb2` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\stability-audit-v1\validated-v3\hy-mt2-30b-a3b-i1-q3-k-l-audit.json` | `3adb3ff50bd57088984dcbd352b8b073bbe5841e507398eb48ee0e7f5e2a9cfc` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\stability-audit-v1\supplement.json` | `5eceb0bfe9fa322691033ee7d89d3b5ee2a423b041d792dad341589d699ad723` |
| `D:\AI_Projects\kototoki\.local\translation-evaluation\hy30-four-20261006\engineering-stability-v1\stability-hy-mt2-30b-a3b-q3-k-m\session\runtime\stderr.log` | `30aa021d85604781da7c75ffcda97ca7938b75db6b20d65dc328fa4577940f67` |

本附录未读取或输出候选字幕文本，未运行模型、网络获取、测试或新性能测量。
