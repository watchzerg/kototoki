# 日语长音频／视频及对应文字的公开来源

- 状态：exploratory；来源核验已完成，素材尚未下载或听辨。
- 更新日期：2026-10-05。
- 范围：为现有两部带日文字幕的电影补充日语 ASR 评测素材，优先保留真实连续长录音与对应日文文字；本记录不改变 W0／X0 基线。
- 来源访问日期：以下网页均于 2026-10-05 查阅。
- 相关文档：[STT 质量与性能评估](../testing/stt-evaluation.md)、[当前电影参考优先级](../testing/fatestay-reference.md)。

后续补充：[YODAS2 日语元数据实查与选样](2026-10-05-yodas2-japanese-selection.md)已统计两个子集的全部时长、体积，并核对部分长录音字幕。本文首次调查中“未读取时长清单”的限制已由该补充解决；音频仍未下载／听辨，上传者字幕及翻译字幕风险继续适用。

后续获取：用户已选择 YODAS2 国会讨论，指定音频／字幕已下载并核验，见[素材记录](../testing/yodas2-parliament-reference.md)；尚未听辨。本文其余内容保留首次来源调研状态。

## 结论与选择原则

公开资料确实很多，但必须区分“整段长录音”“许多短句累积的总时长”，也必须区分“人工听写真值”“上传者字幕”“原书文字”和“ASR 自动字幕”。为了验证整片分段、漏识别、重复、长时间稳定性，优先取原始连续录音；把随机短句拼成两小时不会保留这些问题的真实分布。以下建议属于评测素材建议，尚未成为固定评测集。

在语料库中，**YODAS2 的日语 `ja000` 是最直接的免费长录音入口**：提供完整视频级音频及有时间戳的日文字幕。需要先抽听核对字幕来源与内容覆盖。**CEJC 的付费原始资料是更可靠的自然对话入口**，有音视频和研究级转写，但不属于无需申请的免费下载。**TEDxJP-10K 是适合准确率比较的人工复核补充集**，其人工修订仅覆盖被选中的短片段，不能直接当作所有完整演讲的全文真值。

## 推荐取用次序

若优先考虑低成本实际取用，建议先试下面的 LibriVox 长书与 4989 American Life，再筛 YODAS2 的不同说话者长录音。前两者已经核对到音频入口和对应文本入口；本轮未实际下载、解码或听辨。

## 可直接定位的有声书、播客与录像

| 来源／具体素材 | 长度口径 | 音频与文字入口 | 评测价值与限制 |
| --- | --- | --- | --- |
| 夏目漱石《明暗》 | 全书 16:39:29，按章节提供；不是一次不间断录制 | [LibriVox](https://librivox.org/meian-by-soseki-natsume/)／[对应青空文库原文](https://www.aozora.gr.jp/cards/000148/files/782_14969.html) | 最适合先建立超长输入测试；单人文学朗读，与影视声学场景不同 |
| 夏目漱石《こころ》 | 全书 08:46:41，章节音频及整书下载入口 | [LibriVox](https://librivox.org/kokoro-by-soseki-natsume/)／[对应原文](https://www.aozora.gr.jp/cards/000148/files/773_14560.html) | 文字可直接取得，但没有人工声学时间标注 |
| 夏目漱石《坊っちゃん》 | 全书 04:26:27；11 章，各约 18–32 分钟 | [日语 LibriVox 版本](https://librivox.org/botchan-by-soseki-natsume-2/)，页面有 Online text | 可先单章验收，再全书；不要误选同名英文译本 |
| 4989 American Life | 已核验官方列表 EP.380–383 分别约 26、35、34、37 分钟 | [作者音频发布页，含 Download 与 RSS](https://americanlife4989.podbean.com/)／[作者 Script](https://www.4989americanlife.com/blog) | 现代日语日常话题、女声，补充古典男声朗读；作者稿仍需核查逐字覆盖 |
| 日本众议院预算委员会公听会，2025-02-25 | 官方录像标为 7:00:00；时长可能包含休会／空白 | [具体录像](https://www.shugiintv.go.jp/jp/index.php?deli_id=55534&ex=VL&media_type=)／[国会会议录](https://kokkai.ndl.go.jp/) | 长时多说话者；会议录不是音轨字幕，需匹配会次、院别、日期、会议名并核对整理差异 |
| 东京大学 KYOSS「大学で『文学』を学ぶってどういうこと？」 | 活动安排为 2022-09-19 14:00–16:00；实际视频长度未核验 | [主办方视频与分说话者文字稿同页](https://www.p.u-tokyo.ac.jp/cbfe/kyoss/20220919event_report/) | 三人讨论与问答候选；网页含编辑性括注，不能直接把所有字符当口述文字 |

### 有声书：最长且取用路径最清晰

LibriVox《明暗》原目录已核对到 16:39:29、朗读者 ekzemplaro、整书 ZIP 与分章播放入口；《こころ》《坊っちゃん》的日语目录也列出长度、下载和 Online text。[明暗目录](https://librivox.org/meian-by-soseki-natsume/)、[こころ目录](https://librivox.org/kokoro-by-soseki-natsume/)、[坊っちゃん目录](https://librivox.org/botchan-by-soseki-natsume-2/)

使用原书全文前须去除青空文库的注音、编辑注、底本信息，并听辨朗读是否包含报幕、章名、漏读或不同版本措辞。顺序合并同书原章节可以做全书吞吐和长输入稳定性测试，但应记录章间接缝，不能宣称为十几小时连续自然会话。上述三本是同一朗读者，长度增加不等于说话者多样性增加。LibriVox 标注美国 public domain，并要求其他地区用户核对当地状态；这与“所有国家所有用途均无条件开放”不同。

### 播客：已验证音频与作者稿确实配对

4989 的官方 Podbean 页面直接链接作者 Script，提供单集下载入口和 RSS。已打开 EP.382「誕生日と焼き鳥と。頭の中の整理の話」的完整网页稿，与官方音频列表标题一致，音频标为 34 分钟。[音频目录](https://americanlife4989.podbean.com/)、[EP.382 原稿](https://www.4989americanlife.com/post/ep-382-%E8%AA%95%E7%94%9F%E6%97%A5%E3%81%A8%E7%84%BC%E3%81%8D%E9%B3%A5%E3%81%A8%E3%80%82%E9%A0%AD%E3%81%AE%E4%B8%AD%E3%81%AE%E6%95%B4%E7%90%86%E3%81%AE%E8%A9%B1)

这里确认的是作者发布的对应文字稿，并未证明其制作完全不使用 ASR、逐字保留所有语气词或覆盖每一秒。博客的“19 min read”是阅读时间，不是音频长度。没有核验为开放再分发许可；正式发布评测集时应保留来源与分发边界。

### 国会与大学：天然长场景，但获取和真值准备更多

众议院同一天的官方列表还列出总务委员会 5:30、财务金融委员会 7:14、政治改革特别委员会 2:47，说明可以从官方按日期／会议检索持续寻找长场景。[2025-02-25 录像列表](https://www.shugiintv.go.jp/jp/index.php?ex=VL&u_day=20250225) 国会图书馆 API 可返回会议／发言级日文正文、说话者、日期等；其字段不是秒级音频时间戳。[官方 API](https://kokkai.ndl.go.jp/api.html)

本轮确认了公开视频和会议录系统的入口，没有完成该场会议录与录像的逐项配对，也没有验证可供本地离线 ASR 使用的下载方式与许可。参议院还明确说明播放器字幕由语音自动识别产生、可能误识别，应与正式会议录区别。[官方字幕说明实例](https://www.webtv.sangiin.go.jp/webtv/detail.php?sid=8951)

东大活动主办页同时提供视频链接和多人文字稿，活动安排两小时；视频抓取未成功，故不将两小时写成已验证媒体时长。该类无障碍活动记录是进一步寻找多人长音视频的好方向，但正文里的笑声说明、舞台括注、整理删改都需逐项处理。

## 研究语料与数据集明细

| 来源 | 真正可获得的长度 | 文字及时间信息 | 获取方式／适用范围 |
| --- | --- | --- | --- |
| [YODAS2](https://huggingface.co/datasets/espnet/yodas2) | 每条为完整 YouTube 视频级音频，未切分；具体日语最长样本本轮未核验 | `utterances` 含文字、开始／结束秒数 | Hugging Face，CC BY 3.0；优先 `ja000` |
| [CEJC](https://www2.ninjal.ac.jp/conversation/cejc.html) | 全库 200 小时、577 段会话；单段多为分钟至约一小时 | 研究级转写，另有视频／音频及注释 | 完整音视频需付费合同；免费系统不能下载录音 |
| [CSJ](https://clrd.ninjal.ac.jp/csj/data-index.html) | 全库 661 小时、3302 篇讲演等；全库平均约 12 分钟／条，由总量计算 | 全部音频有转写，汉字假名与细节片假名两种表示 | 完整离线版付费；官方有少量免费 MP3／文字样本 |
| [TEDxJP-10K](https://github.com/laboroai/TEDxJP-10K) | 10,000 个抽选片段；原演讲音频可以完整获取 | 人工检查并修订文字与时间戳 | 公开 URL 清单、重建脚本和修订数据，视频可用性需逐条核对 |
| [JTubeSpeech](https://github.com/sarulab-speech/jtubespeech) | 日语上传者字幕视频清单：约 11 万视频／1 万小时，统计为 2021 年收集时口径 | 清单区分 `sub` 上传者字幕与 `auto` 自动字幕 | 主要发布视频 ID 与脚本，须从原平台重新获取 |
| [ReazonSpeech](https://huggingface.co/datasets/reazon-research/reazonspeech) | 当前数据卡为约 35,000 小时总量，公开格式是切好的音频片段 | 电视字幕经自动对齐／过滤，非逐段新人工听写 | 有 tiny 到 all 五档；适合短段补充，不优先用于长片 |
| [YODAS3](https://huggingface.co/datasets/espnet/yodas3) | 整视频音频；全语言均值约 952 秒，最长约 42.6 小时，均不能直接当作日语统计 | 原语字幕约 95% 为 ASR 轨，带词级偏移；上传者字幕通常无词级偏移 | 新发布的大规模数据，适合压力测试；主真值可靠性弱 |

### YODAS2：最接近需求的免费长音频语料

官方数据卡确认：每条保存完整、未切分的原视频音频，24 kHz，包含 `duration` 与 `utterances[{text,start,end}]`。`video_id` 是语料自己的 ID，并非原 YouTube ID。[数据卡](https://huggingface.co/datasets/espnet/yodas2)

日语 `ja000`、`ja100` 配置已在官方元数据中确认存在，分别有 211 和 303 个底层 shard。[官方 meta.py](https://huggingface.co/datasets/espnet/yodas2/blob/main/meta.py) 原 YODAS 的命名规则以首位 `0` 区分上传者字幕、`1` 区分平台自动字幕；原库日语短切片合计分别为 1094.18 与 2929.94 小时。**这些不是 YODAS2 完整原视频音频时长统计**。官方还明确：manual 仅代表用户上传，不能保证由人工转写。[原 YODAS 数据卡](https://huggingface.co/datasets/espnet/yodas)

可行的后续选取方式：先读取 `ja000` 的 `duration/*.txt` 和 `text/*.json`，筛出至少 30／60／120 分钟的样本，检查日文文本覆盖，再获取少量对应音频。官方 loader 支持 streaming，但页面提示依赖自定义 Python 加载代码；本轮没有实跑或核验本机 `datasets` 版本兼容性。[官方 loader](https://huggingface.co/datasets/espnet/yodas2/blob/main/yodas2.py)

不确定性：未读取完整日语时长清单，因此没有确认日语最长值、长于一小时的数量或字幕覆盖率；未听辨 `ja000`，不能将整个子集称为人工金标准。

### CEJC：真实多人日常对话

CEJC 的官方设计为 200 小时、577 段会话、862 名不同说话者；录制目标一般为每次约一小时以内，但整理时会切除不可公开部分。全库平均约 20.8 分钟／会话，是总量除以段数的推算值。[设计与构成](https://www2.ninjal.ac.jp/conversation/cejc/design.html) 官方列表有 `C001_003`：两人家庭咨询，46 分钟；`C001_007`：三人晚饭交谈，51 分钟；`C002_015`：三人直播场所闲聊，64 分钟。[会话清单](https://www2.ninjal.ac.jp/conversation/cejc/convList.html)

免费“中納言”需申请，能听检索位置附近的声音，不能下载音频，不能观看／下载视频。完整原始音频、视频、转写与注释通过付费合同提供。旧的 2018 年 monitor 版已在 2022 年结束，不能拿旧版免费／实费规则描述现在的完整集。[当前获取方式](https://www2.ninjal.ac.jp/conversation/cejc.html)、[付费申请](https://chunagon.ninjal.ac.jp/offlinedataappl?lang=en&target=CEJC)

评测推断：自然多人交谈、抢话、口头语、生活噪声，与影视对白互补；转写中的研究符号需依规范处理，不能直接与 ASR 字符串比较。[转写规范](https://www2.ninjal.ac.jp/conversation/cejc/transcript.html) 本轮未签约，也未核验报价。

### CSJ：正式讲演／自发独白的标准来源

当前第九刷提供 661 小时、3302 条录音，约 90% 独白，其余为对话／朗读。所有录音均有转写，官方离线版通过 256 GB USB 提供。[第九刷说明](https://clrd.ninjal.ac.jp/csj/data-index.html) 完整版需许可费：官网现行表列一般用途 25 万日元未税；商业用途另有收费层级，实际适用类别以合同为准。[现行价格表](https://clrd.ninjal.ac.jp/csj/fee.html)

官方免费样本页有学会讲演、一般演讲、采访、任务对话的 MP3 与对应文字，适合先检查格式。[样本页](https://clrd.ninjal.ac.jp/csj/sample.html) 但已打开的学会转写只覆盖约 34.7 秒并以“略”结束，因此免费样本不能描述为完整长讲演。[实际样本文本](https://clrd.ninjal.ac.jp/csj/trans-f/aps-smp.txt) 同页 CSJ-RDB 样本另有非购买者不能用其发表研究、不得二次分发的提示。

### TEDxJP-10K／JTubeSpeech：讲演与公开视频定位

TEDxJP-10K 作者从带日文人工字幕的 TEDx 视频选出 10,000 个片段，再人工修订文字和时间；公开音频 URL、字幕获取说明、修订数据。[作者仓库](https://github.com/laboroai/TEDxJP-10K) 重建代码保存整条来源 WAV，再用 `segments` 记录选中范围，因此可在整段长音频运行 ASR 后只对人工复核范围评分。[重建源码](https://github.com/laboroai/TEDxJP-10K/blob/main/compose_tedxjp10k.py) 未复核范围应单独标记；历史字幕变更、删片可能导致重建失败。

JTubeSpeech 可作为进一步找长视频的索引：`data/ja/202103.csv` 中 `sub=True` 表示有人上传字幕，`auto=True` 表示有平台自动字幕，可同时为真；仓库主要给清单和获取／对齐脚本。其 11 万个日语有字幕视频、约 1 万小时是历史收集统计，现存比例和单条长度需重新筛选。[官方仓库](https://github.com/sarulab-speech/jtubespeech) 清单本身不保证每个字幕逐字准确，也不保证每个视频可再分发。

### ReazonSpeech／YODAS3：总量很大，但标签需分层

ReazonSpeech 当前卡列 tiny 约 8.5 小时／600 MB、small 100 小时／6 GB、all 35,000 小时／2.3 TB，音频是 16 kHz FLAC 配对应文字，许可为 CDLA-Sharing-1.0 并附特定使用目的要求。[数据卡](https://huggingface.co/datasets/reazon-research/reazonspeech) 2023 论文说明其旧发布版以 utterance 为单位，某一训练发布集限制 14 秒，并随机打乱以防还原节目；该 14 秒限制不能直接认定为当前所有版本上限。[作者论文](https://research.reazon.jp/_static/reazonspeech_nlp2023.pdf) 因而不适合把 35,000 小时理解为可拿到完整电视节目。

YODAS3 是 2026 年新版本，提供整视频音频与字幕元数据，约 95% 有文字样本的字幕轨来自 ASR。全语言最长值、均值不等于日语子集。`transcript` 是原語文字，`translation_en` 是英译，日语评测应只用前者。[YODAS3 当前数据卡](https://huggingface.co/datasets/espnet/yodas3) 本轮未下载日语 metadata，未验证上传者字幕筛选与文本完整性。更适合长音频运行压力验证，主准确率评分优先人工复核材料。

## 长篇有声书的语料桥梁

[Kokoro Speech Dataset 官方仓库](https://github.com/kaiidams/Kokoro-Speech-Dataset) 给出 14 本 LibriVox 日语书录音及青空文库对应原文链接，包括《明暗》16:39:29、《こころ》08:46:41、《田舎教師》08:13:26。派生版本是约 4.48 万个 3–14.861 秒短片段，总 58:41:39，由程序自动切分和对齐；要验证连续长输入，应获取其原始书／章节录音。仓库在 2026-04-14 记录部分 ZIP 失效，可按单章 MP3 获取。原文与朗读版本差异、开场报幕、章节名及时间真值需要另行核对；该派生对齐不能视为人工时间真值。

## 后续冻结素材时要记录的信息

1. 来源 URL、来源页面与音频版本、获取日期、许可及本地文件哈希。
2. 原始连续时长、有效日语语音时长、文字覆盖范围；保留静音、音乐、抢话的真实位置。
3. 标签来源：人工转写、人工修订、上传者字幕、原书文字或自动字幕。
4. 抽听前中后至少若干位置，核查漏句、口头语、省略、翻译与版本差异。
5. CER 的文字规范与时间指标分别记录；字幕显示时间、自动对齐时间、人工声音边界不能合并为同一种真值。

本轮只核验网页与发布结构，没有获取音视频、运行 ASR 或人工听辨；候选的当前可下载性及文字质量仍需在正式选样时验证。
