"""翻译的 llama-server 配置：APEX-I-Compact 冻结资产身份与冻结命令行（`TRANSLATE_SPEC`）。

server 生命周期、身份核对、显存轮询、驻留校验与 HTTP 客户端在 `kototoki/llama_server.py`（票据 02 从本模块抽出，
与专名建表共用）；这里只留翻译特有的常量。命令行与 v3 冻结 C0 相同（`experiments/translation_v3/server.py`）。
`InfraFailure`、`wait_for_free_vram` 再导出，供 `tests/core/test_translate.py` 沿用原导入路径。
"""

from __future__ import annotations

from kototoki.llama_server import InfraFailure, ServerSpec, wait_for_free_vram  # noqa: F401  后两者为再导出

from .recipes import CONTEXT_SIZE

# APEX-I-Compact 冻结资产身份（`translation_demo/run.py` 的 HY30_ASSET_IDENTITIES 对应行）。
MODEL_ASSET = {"repo": "alphaZimuth/Hy-MT2-30B-A3B-APEX-GGUF", "revision": "312cce865e03a0718e36cfd1077e6307957aef72",
               "file": "Hy-MT2-30B-A3B-APEX-I-Compact.gguf", "size": 15035838080,
               "sha256": "8a51a390b285fb1eb566a1683f8da476be9e87c1fbee5507967d6129872dfa1a"}
# 启动前等待的空闲显存（MiB）。2026-10-14 整片实测：会话峰值 15687 MiB、桌面基线约 880 MiB，
# 即 llama-server 自身约 14800 MiB。票据 08 整片验收：桌面占用在 0.6–1.2 GB 间漂移，空闲 14742 MiB 时 server
# 加载后桌面占用由约 1236 降到约 597 MiB、翻译正常（推测为 WDDM 换出，未核实）；用户裁定阈值取 14700（2026-10-15），低于它时等待／失败。
MIN_FREE_MIB = 14700

TRANSLATE_SPEC = ServerSpec(
    stage="translate", candidate="hy-mt2-30b-a3b-apex-i-compact", model_asset=MODEL_ASSET, layers=99,
    context=CONTEXT_SIZE,
    extra_args=("-b", "256", "-ub", "128", "-t", "8", "-tb", "8", "-ctk", "f16", "-ctv", "f16", "--cache-ram", "8192",
                "-fa", "on", "--fit", "off"),
    min_free_mib=MIN_FREE_MIB, load_timeout_s=180)
