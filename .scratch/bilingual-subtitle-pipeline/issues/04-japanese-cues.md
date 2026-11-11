# 04 日文 cue 切分与时间回填

Status: done
Type: task
Blocked by: 00

## 范围

- 架构（[目标架构](../../../docs/architecture/bilingual-pipeline-architecture.md)"日文 cue"行）：`build_cues(align, rules) -> (cues, srt_text)` 是无副作用的纯函数，输入已解析的 `align.json` 内容，不读写文件；`ja-cues.json` 与 `ja.srt` 的写入由编排经产物契约与 `srt.write_srt` 完成。这是时间轴上唯一加 offset 的地方。
- `kototoki/cues.py`：输入 `align.json` 内容，产出 `ja-cues.json` 与 `ja.srt` 的内容。
  - 坐标：按 00 的约定，`units.start/end` 已含 `offset_s`，窗口与 VAD 子段是本地坐标；粗回退时把子段加一次 `offset_s`，不重复加。
  - 回填（先于切分）：窗内零散 `text_only` 字符按相邻有时间字符线性插值（`time_source=interpolated`）；窗首或窗尾只有单侧邻居时按同样的每字符时长向窗口边界外推，不越过窗口边界；整窗无时间时按该窗内 VAD 子段（manifest `segments`）分配并对每字符时长设上限（`time_source=fallback`，沿用 `kototoki_eval.schema` 取值，不新造 `coarse`）；记录每个 unit 的来源。
  - 切分：句末标点与 `max_gap_s` 断句 → 超 `max_chars` 在 `soft_breaks` 后切 → 仍超则硬切；`max_duration_s` 超限同样切。
  - 时间修饰：`lead_out_s`，不越过下一条起点；`min_duration_s` 向后延长不重叠。
  - 不产出空 cue、纯标点 cue；♪ 等符号与标点一并视为非词汇字符附着到相邻 cue；全部不可渲染时产出零条目 SRT。
  - `ja-cues.json`：每条 cue 的 unit 范围、字符范围、时间来源统计、回填字符数。

## 完成标准

- 离线测试（`tests/`）：回填、边缘外推、三级切分、lead-out 不重叠、min-duration、空输入、全 text_only 窗、纯标点、♪，以及**非零 `offset_s` 下 offset 只加一次**。
- 用 `.local/fullfilm-comparison/` 现有 `result.json` 离线产出 `ja.srt`，人工看 5 分钟，记录观感与要调的参数。

## 文件所有权

`kototoki/cues.py`、对应测试；`kototoki/recipes.py` 的 `CUES` 节（2026-10-14 用户裁定：04 可修改，用于补整窗 `fallback` 每字符时长上限等 cue 算法常量）。

## Comments

- 2026-10-13 建票，依据规格 §12。
- 2026-10-14 按两轮评审修订（规格 §13）。
- 2026-10-14 第三轮评审：坐标约定、边缘外推、`fallback` 命名、非零 offset 测试。
- 2026-10-14 实现完成（分支 `feat/bilingual-04`）：`kototoki/cues.py` 的 `build_cues(align, rules) -> (payload, srt_text)` 纯函数，接口与架构页一致，未偏离；`tests/test_cues.py` 23 个 core 测试覆盖完成标准全部条目；新建模块页 [日文 cue](../../../docs/architecture/modules/japanese-cues.md)，架构页、架构总览、模块边界同步。
  - 实现取舍（规格未写明、由实现方给出）：`rules` 取与 `[cues]` 表同形的映射（键集合严格），供票据 02 的配置直接传入；`max_chars` 按非空白码点计、含附着标点（规格 §5.2）；边缘外推的"每字符时长"取该窗首末有时间字符跨度的平均值；整窗回退按 VAD 子段时长比例（最大余数法）分配字符、每字符上限 `FALLBACK_MAX_CHAR_S = 0.25` s；软断点取使前段不超限的最后一个；硬切按所需段数均分；非词汇字符为 Unicode P／S／Z／C 类（含 ♪），相邻词汇字符间的非词汇串在第一个空白或开括号处分给前后两条；cue 时间只取词汇字符，避免句末标点被插值拉进间隙；取整后零时长补 1 ms。
  - `FALLBACK_MAX_CHAR_S` 会改变输出，应进 cue 配方 hash；`kototoki/recipes.py` 归票据 02，本票未动，交 02 收编（或迁入 recipes.py）。
  - 离线观感（规格 §5.2 初值，`.local/fullfilm-comparison/fullfilm-v1/runs/w0-pyannote-current-hf-ii-full/align/alignment.json`；该处没有名为 `result.json` 的文件，`alignment.json` 是同一结构；输出只写在会话临时目录，未进仓库与 `.local/`）：整片 1627 条，0 重叠、0 条超 6 s，412 字插值、1 窗 5 字 `fallback`。前 5 分钟观感：句子级切分自然（"セイバーに付き合ってたんじゃなくて"／"俺がセイバーを付き合わせてたんだ"），但 `max_gap_s = 0.4` 在 CTC 字间间隔处把词切碎（"先｜輩…"、"なん｜だ?"、"で｜も…"），≤2 字条目 374 条。同一输入 `max_gap_s` 0.6／0.8／1.0／1.5 时 ≤2 字条目为 199／157／123／65、中位字数 6.5／7／9／12。建议把 `max_gap_s` 初值调到约 1.0（待用户裁定，属配置键，不改代码）。另见 3:13 前后"セ｜イバーさん｜の帰国…"跨数秒，是该窗 MMS 对齐本身的时间离散，cue 规则无法修复；Whisper 输出 `。` 很少、多用 `…` 与空格，二者不在 `sentence_endings`，按间隔断开。
  - 遗留：编排器写 `ja-cues.json`／`ja.srt` 及身份包装归票据 06；Qwen（x0）输出下的切分观感待票据 07；票据 02 的延迟音轨端到端断言会经过本函数。
- 2026-10-14 用户裁定：全部采纳上述建议——`max_gap_s` 初值改 1.0（规格 §5.2／§10.1 已改）；`FALLBACK_MAX_CHAR_S` 交票据 02 收编进 cue 配方 hash；`rules` 映射形式与各实现细节接受。分支已合并入 main。
- 2026-10-14 用户裁定（票据 02 收尾）：本票可修改 `kototoki/recipes.py` 的 `CUES` 节，其余节仍归 02。
