# 四部电影的日语评估参考与素材保护

状态：已接受的当前语料优先级与素材保护规则；历史语料身份及清洗证据保留  
最后更新：2026-10-04  
范围：本机外部评估音频、日文 SRT 的来源、可信度、身份及使用边界。

## 当前评估语料与优先级

用户于 2026-10-04 明确指定以下参考等级。后续模型对比优先使用
Heaven’s Feel II 和 III，两部共同构成主要评估语料；Heaven’s Feel I 和
Black Panther 仅用于补充参照。来源与可信度判断来自用户提供的信息，
本次文件盘点和哈希计算只确认文件身份。

| 影片 | 用户说明的 SRT 来源 | 当前用途 |
| --- | --- | --- |
| `FateStay Night Heaven’s Feel II` | 从原版内嵌日文字幕提取，精确参考样本 | 主要参考，优先用于文字质量和字幕时间对比 |
| `FateStay Night Heaven's Feel III` | 从原版内嵌日文字幕提取，精确参考样本 | 主要参考，优先用于文字质量和字幕时间对比 |
| `FateStay Night Heaven's Feel I` | 从中日双语字幕抽取日文，可信度稍差 | 补充参照，结果单独列出，疑点需复核 |
| `Black Panther` | 英文电影，提取日语音轨和日语内嵌字幕，可信度最差 | 补充诊断；配音与字幕可能措辞不同，未经听辨核对的字幕不作为逐字评分真值 |

“精确参考样本”是用户对 II/III 来源及文字可信度的指定，不代表已完成逐句听辨，
也不代表 SRT 的显示时间就是词级声学边界。文字质量、字幕显示时间差和精确发声
起止误差应分别报告。画面文字、歌词、音效说明、未发声内容或编辑对白，
在派生评估标注中单独处理，保留源 SRT。

[四部电影低成本核验](2026-10-04-media-matching.md)已确认四份外置音轨的全片编码内容
与相应视频日语音轨一致，并完成内置字幕对照和 12 段机器辅助抽查。
这些核验支持当前音频的来源身份；Black Panther 存在配音与字幕措辞不同的疑点。
四部均尚未完成逐句人工听辨及精确声学边界验证。

## 当前音频输入与 SRT 身份

视频音频已分离完成。后续识别直接读取各影片文件夹中的现有日语音频，
无需再次从 MKV 提取音轨。后端需要的解码、采样率转换、下混和裁剪从这些音频
生成派生输入，记录处理方法、样本范围与源时间映射；派生文件写在 `D:/movie/` 之外。
视频仅在需要检查素材来源、画面或口型等具体问题时只读使用。

以下路径、字节数和 SHA256 于 2026-10-04 通过只读盘点核对。
II 的路径使用弯撇号 `’`，I/III 使用直撇号 `'`，调用时按实际文件名保留。

| 影片 | 现有音频输入 | 当前日文 SRT | 音频字节数 | SRT 字节数 |
| --- | --- | --- | ---: | ---: |
| II | `D:/movie/FateStay Night Heaven’s Feel II/FateStay Night Heaven’s Feel II.jpn.flac` | `D:/movie/FateStay Night Heaven’s Feel II/FateStay Night Heaven’s Feel II.jpn.srt` | 1223709384 | 73843 |
| III | `D:/movie/FateStay Night Heaven's Feel III/FateStay Night Heaven's Feel III.jpn.flac` | `D:/movie/FateStay Night Heaven's Feel III/FateStay Night Heaven's Feel III.jpn.srt` | 1232989435 | 72171 |
| I | `D:/movie/FateStay Night Heaven's Feel I/FateStay Night Heaven's Feel I.jpn.flac` | `D:/movie/FateStay Night Heaven's Feel I/FateStay Night Heaven's Feel I.jpn.srt` | 1486155550 | 72671 |
| Black Panther | `D:/movie/Black Panther/Black Panther.jpn.eac3` | `D:/movie/Black Panther/Black Panther.jpn.srt` | 309718016 | 111492 |

| 当前 SRT | 完整文件 SHA256 |
| --- | --- |
| II | `8366D17A2F0523FD1A82973736C18094D985ABB95C3693B57E2A27517BADF57D` |
| III | `7C778CBD405E362FC659B237F870C5687AD5EA739E09509747575BD697A4CCBF` |
| I | `E2697ADC9101C4897038732DC45FAD8E3D77527812E7D56B838E8387E43E90AD` |
| Black Panther | `857464F277C9603FE28ABE4AA61E12FE109107E0F68691B953C22BF2530547BB` |

哈希覆盖完整文件，包括编码及换行；不能独立证明字幕内容、提取来源或声学同步。
音频字节数用于盘点，不是加密身份。每轮评估应记录实际所用音频的哈希或可核查的
既有身份记录，并记录送入模型的 PCM 身份。上述绝对路径属于本机私有外部素材，
不是可移植的应用默认路径，也不是应提交到 Git 的文件。

<a id="preserve-originals"></a>

## 原始素材保护

评估期间把整个 `D:/movie/` 视为只读输入位置：

1. 直接读取现有音频；视频、音频和字幕不得移动、重命名、覆盖或改变文件属性。
   不为评估复制整部视频到项目，也不重复提取已有音轨。
2. 源 SRT 仅供参考，不在原路径规范化、重编码或修订。评估前后重新计算所用 SRT
   的 SHA256，与上面的当前基线比较；不一致时调查并报告，不能静默刷新基线。
   经明确授权替换参考后，须记录新的身份及适用轮次。
3. 转录、解码音频、裁剪、评分规范化文本、人工标注和报告写入事先指定的
   `D:/movie/` 之外的输出位置。运行前检查工具自动命名的输出路径，避免覆盖源文件。
   私人或大型产物不得进入 Git 和常规日志。
4. 必要修订保存为派生标注或工作副本，关联原始 SRT 哈希和条目身份。
   原始参考保持不变，声学边界标注与显示时间分开保存。

例如，核对主要参考 II 的哈希：

```powershell
Get-FileHash -LiteralPath "D:/movie/FateStay Night Heaven’s Feel II/FateStay Night Heaven’s Feel II.jpn.srt" -Algorithm SHA256
```

这些文件名包含撇号，PowerShell 示例使用双引号包围路径；使用 `-LiteralPath`
避免把文件名中的特殊字符当成通配符。

## 后续模型对比流程

1. 先确认所选主要参考 II/III 的现有音频和 SRT 身份、音频时间原点及输出位置。
   无需重新选择或提取视频音轨；对解码和裁剪保留原音频时间坐标。
2. 查看候选输出之前冻结 II/III 的区间或整片范围、开发/验证/保留划分、归属规则
   和评分规范化。各候选使用同一组输入。现有单片实验不能自动扩展为 II/III
   联合评估；新轮次另建 manifest，不能将旧保留结果重新解释为新轮次证据。
3. 识别现有日语音频，保持日语转写，不向正在评分的识别流程提供参考正文、
   修订文本或参考引导提示。固定参考文本的强制对齐另记为对齐实验。
4. 按[评估方法](stt-evaluation.md)和[字幕时间基准](subtitle-timing-benchmark.md)
   评价完整文字、覆盖和失败。依据文字/发声身份匹配时间，允许已记录的分段差异；
   不按 SRT 序号匹配，也不只挑成功匹配的条目评分。
5. 对 II/III 分别报告结果、参考字数和失败分母，再按预先规定的规则汇总主要语料。
   I/Black Panther 单列补充结果；不与主要参考混成一个未分级的总分，也不让较低
   可信度的字幕差异直接决定模型排名。补充文本评分须声明已核对的范围和剩余歧义。
6. 与源 SRT 起止时间的差报告为“参考字幕时间差”。需要精确声学评价或争议复核时，
   听辨并记录独立的可听起止边界及不确定性，不用显示时间代替声学真值。
7. 复核所用参考哈希，记录模型、实际 GPU 执行、音频及 PCM 身份、配置和范围。
   两部主要参考的结果仍不能证明所有语言、影片或工作负载的质量。

本次更新确定语料优先级及现有音频输入方式，没有新建冻结样本集、重跑推理或建立
新的数值验收门槛。小型合成样本继续用于离线单元测试。

## 历史字幕清洗记录（2026-10-04）

此前用户授权清洗四部电影已提取的日文 SRT，严格保留日语句子时间戳。
当时按授权在原路径清洗，并在修改前对四份字幕作逐字节备份；这是源文件维护，
不改变后续评估的只读保护规则。第一轮标签及声明清洗记录如下：

| 电影目录名 | 清洗后条目 | 操作 |
| --- | ---: | --- |
| `Black Panther` | 1654 | 删除原条目 1654 的日文字幕制作署名 |
| `FateStay Night Heaven's Feel I` | 1070 | 无需清洗，文件字节不变 |
| `FateStay Night Heaven’s Feel II` | 1026 | 无需清洗，文件字节不变 |
| `FateStay Night Heaven's Feel III` | 1038 | 移除字体、粗体和定位标签；删除原条目 1/2/3/5 的中文声明署名及 1012 的空条目 |

历史记录中的第一轮备份与审计位置为 `D:/movie/_subtitle_cleanup/2026-10-04/`：
`originals/` 存放原文件，`audit.json` 记录前后 SHA256、删除原因、原编号映射及
逐条时间戳核对结果，`README.md` 为摘要。该轮记录显示全部 4788 条保留字幕的
时间戳字符串与各自原文件完全一致，保留正文除移除标签外未改写；未发现其他中文
翻译残留，画面文字、歌词和原有英文内容保留，未进行声学核对或纯对白标注。

同日按追加授权进行第二轮空白清理：去除日语正文中的半角、全角及 U+2000
排版空白；英文咒文、歌词的词间空白统一为单个半角空格，避免单词粘连。
该轮未发现 Cf/Cc 不可见控制或格式字符。四份文件均更新，合计修改 1788 条正文，
空白字符由 2747 个减少至 64 个英文词间空格；全部 4788 条时间戳、编号、换行及
非空白文字保持不变。历史备份和审计位置为
`D:/movie/_subtitle_cleanup/2026-10-04-whitespace/`，其中 `originals/` 是第一轮结果，
`audit.json` 的 `after_sha256` 记录第二轮结果身份。

本次只读检查未在这两处旧路径找到 `audit.json`；上述位置保留为历史记录，
不能保证备份和审计当前仍可读取。当前可核对身份以上面的实际 SRT 哈希表为准。

## 历史默认输入及冻结身份（2026-10-03）

用户此前指定的默认组合为 `D:/movie/FateStay/FateStay.mkv` 和
`D:/movie/FateStay/FateStay-original-1.srt`；后者当时被说明为从原片提取的日文文本轨。
`FateStay-original-2-ocr.srt` 来自图形日文字幕 OCR，含识别错误。
Stone/Dr. Stone 和 KonoSuba 当时是按需补充素材。
这些历史默认输入已经由本文件的当前四影片规则取代，旧 `FateStay/` 路径当前不存在；
旧 OCR、Stone、KonoSuba 不属于当前常规比较要求。

以下保留 2026-10-03 的只读盘点及完整字幕哈希，供历史 manifest 和实验追溯，
不作为新评估输入或当前 SRT 基线：

| 历史角色 | 当时路径 | 字节数 |
| --- | --- | ---: |
| 默认视频 | `D:/movie/FateStay/FateStay.mkv` | 4576084233 |
| 默认日文文字及时间参考 | `D:/movie/FateStay/FateStay-original-1.srt` | 75664 |
| 辅助日文 OCR 参考 | `D:/movie/FateStay/FateStay-original-2-ocr.srt` | 101268 |
| 可选中文参考 | `D:/movie/KonoSuba/KonoSuba God's Blessing on this Wonderful World! Legend of Crimson (2019).ass` | 138530 |
| 可选中文参考 | `D:/movie/石纪元/[DBD-Raws][石纪元][01][1080P][BDRip][HEVC-10bit][FLAC].SC.ass` | 29393 |

| 历史字幕 | 历史 SHA256 |
| --- | --- |
| FateStay 文本 SRT | `2D31B51406DD33CFC3AF300C9346280A31AAC7B6C199208E87F1F92CE79AE583` |
| FateStay OCR SRT | `2C9E12E1FB9F7B479864DF88D85DA43F36B588EFDD71201082D7D5904B321D5F` |
| KonoSuba ASS | `0BE5E2531418492A00BB297D3EC399E1E07FDD35ED6A26FD629131EE27433F6E` |
| Stone ASS | `F64559FB63905021EA9AB6C66429D6F1D68A47506301AF4D9FF0F3BF7F70A938` |

KonoSuba 和 Stone 的历史值与相邻项目的
[参考记录](../../../subtitle-edit-fix/docs/research/2026-10-02-reference-subtitle-validation.md)
一致。该次记录没有进行视频哈希、音轨选择、时长探测、声学复核或模型推理；
视频大小仅为盘点信息。不能用当前路径或当前哈希覆盖历史 manifest、参考身份
或实验分数。历史研究中的旧路径只在对应实验范围内解释，新评估使用本文件的
当前音频和 SRT 身份，并建立独立记录。
