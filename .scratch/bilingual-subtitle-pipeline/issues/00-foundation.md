# 00 产物契约、worker 协议与 SRT 基础

Status: done
Type: task
Blocked by: —

## 范围

- `kototoki/artifacts.py`：
  - 工作目录 id：相对路径（含扩展名）SHA256 前 12 位；`.work/index.json` 维护 id ↔ 相对路径。
  - 每种产物的文件名常量、`identity` 结构与读写：视频身份 = 相对路径＋大小＋修改时间＋ffprobe 指纹（只取流的 `index`／`codec_name`／`channels`／`channel_layout`／`sample_rate`／`start_time`／`duration` 与容器 `duration`，不含 `filename` 与 `tags`）；派生产物身份 = 上游产物 SHA256＋配方 hash＋模型文件 SHA256＋影响输出的配置键（cue 规则、seed）；绝对路径不参与。模型文件 SHA256 走 size+mtime 缓存（`.work/cache/model-verification.json`，取自 v3 `server.py::verify_model`），每次运行最多算一次。
  - **坐标约定**（规格 §4）：逐产物写明字段坐标。`vad.json`／`asr.json`／`align.json` 的窗口、段、对齐记录为 WAV 本地秒／整数样本，顶层 `offset_s`（产品恒为 0）；只有 `align.json` 的 `units.start/end` 含 offset（与现有 `result.json` 一致）；cue 时间为最终 SRT 时间。
  - `is_current(artifact, expected_identity)` 匹配即跳过，不匹配时原地原子替换（`translate/` 目录除外，见 05）；`failure.json` 写法。
  - `published.json`：三份 SRT 的 SHA256、来源产物身份、当前使用的 `translate/srt-<sha12>` 目录。**覆盖规则**：三份现有最终文件都未被改动（SHA256 等于记录）或不存在即可替换；任一被改动且非 `force` 则拒绝，判定函数供 06 在扫描阶段调用。
  - 原子写（临时文件＋替换，Windows `PermissionError` 重试，取自 `experiments/translation_v3/common.py`）。
- `kototoki/workers/protocol.py`：`--jobs <json>` 输入格式（文件列表、各自输入产物路径、配置快照、配方 hash）；worker 逐文件增量写结果并在 stdout 打一行进度 JSON（UTF-8）；单文件异常记失败并继续下一文件；退出码：0 全部完成、1 部分文件失败、2 启动失败或 CUDA 粘性错误（后续文件必然失败，由编排器重启）。ASR 结果的 `failed_windows` 字段（w0／x0 共用）：窗口失败时该窗 `text` 置空，截断文字与原因记在 `failed_windows`，不进对齐与 cue（规格 §6）。
- `kototoki/srt.py`：从 `experiments/translation_flow/srt.py` 复制解析／写出，允许零条目；UTF-8 无 BOM；毫秒取整用 `replay.py` 的 `floor(x*1000+0.5)`，不用 Python `round`。
- 接线：建 `tests/__init__.py`（产品 core 测试统一放 `tests/`，`just test` 发现）；`justfile` 的 `check` 加 `kototoki`。这两处是本票的文件所有权，01 不动。

## 完成标准

- 离线 unittest（`tests/`）覆盖身份匹配与失效、短 id 碰撞、模型哈希缓存命中／失效、覆盖规则四种组合、原子写重试、协议解析与 `failed_windows`、空 SRT 读写、毫秒取整边界。
- `just check`、`just test` 可运行。
- 模块边界文档加"产物契约"归属行。

## 文件所有权

`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`、`tests/__init__.py`、`tests/test_artifacts.py` 等对应测试、`justfile` 的 `check`／`test` 两行。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：加坐标约定、覆盖规则、模型哈希缓存、`failed_windows`、取整规则、`tests/` 与 `just check` 接线。
- 2026-10-14 实现（分支 `feat/bilingual-00`）：`kototoki/artifacts.py`、`kototoki/workers/protocol.py`、`kototoki/srt.py`，另建包标记 `kototoki/__init__.py`、`kototoki/workers/__init__.py`（无他票归属）；测试 `tests/test_artifacts.py`、`tests/test_protocol.py`、`tests/test_srt.py` 共 61 个，离线通过；`justfile` 的 `check` 加 `kototoki`（`test` 行原已发现 `tests/`，未改；`tests/__init__.py` 在 b2fe9a6 已存在）。文档：新建模块页 `docs/architecture/modules/artifact-contract.md`，架构总览模块地图与模块边界加"产物契约"行，`workflow.md`／`toolchain.md` 去掉"`tests/` 为空"的过时说明。
- 实现取舍：`published.json` 增加 `previous_sha256`（写记录时最终位置上已有文件的 SHA），保证"写记录后、移动前崩溃"（可连续多次）时旧文件不被误判为用户改动；规格 §4 未写此字段，属实现补充。`record_published` 须在 `publish_blockers` 放行后、移动文件前调用。CUDA 粘性错误的识别由各 worker 包装为 `FatalWorkerError`（03／07）。`srt.py` 保留 `render_srt`／`validate_translations` 与 `<sha8>-cue-<n>` 别名，供 05 移植 v3 时保持请求字节不变。
- 与旧代码的差异（以规格为准）：`parse_srt` 空输入返回零条目而非报错；`write_srt` 改为原子覆盖写（v3 为 `open("x")` 拒绝已存在），覆盖与否交给 `publish_blockers`；`atomic_write_text` 失败时删除临时文件。
- 遗留：①验证时根项目已被并行进行的 01 改为 Python 3.13＋torch 依赖，`uv run --locked` 在 `uv sync` 前不可用，本票测试改用 `uv run --no-project --python 3.12／3.13` 运行（stdlib only，两版本均通过）；01 完成同步后需重跑 `just check`／`just test`。②`failure.json` 在重跑成功后的清理规则归 06。③Windows 真实文件占用下的替换重试只用注入的 `replace` 模拟。
- 2026-10-14 用户裁定：采纳 `previous_sha256` 并写回规格 §4；`srt.py` 保留翻译侧函数供 05；`failure.json` 清理归 06（已记入 06 Comments）；并行票据今后各用独立 worktree。
