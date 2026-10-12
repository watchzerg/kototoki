# Hy30 流程实验的参数与接口核对

2026-10-07 核对；固定 ADR-0005 的 APEX-I-Compact，不代表采纳新参数。
实际运行与选择见[探索台账](../context/2026-10-07-hy30-flow-exploration.md)。

## 官方建议与本机映射

[Tencent 30B README](https://huggingface.co/tencent/Hy-MT2-30B-A3B/blob/main/README_CN.md#推理和部署)
推荐 temperature=0.7、top_p=1.0、top_k=-1、repetition_penalty=1.0、max_tokens=4096。
同页 Transformers 示例使用 max_new_tokens=4096，因此该数值是生成上限，不是总 context。
不要混用该页 7B 的采样建议。

本机固定 llama.cpp b11429／d81235049384534c167caea52b85a694f6103d14 兼容 loader。
原生 `/completion` 使用 `repeat_penalty`、`n_predict`；
本地 `tools/server/server-schema.cpp:89` 将 top_k 限定为非负，并说明 0 禁用。
底层 sampler 能处理非正值，不等于 HTTP schema 接受 -1；实际请求用 0。
[固定版本 server 文档](https://github.com/ggml-org/llama.cpp/blob/b11429/tools/server/README.md#post-completion-given-a-prompt-it-returns-the-predicted-completion)
与本地 `common/sampling.cpp` 共同说明 sampler 列表控制实际采样链。

当前显式官方族：`temperature=0.7, top_p=1, top_k=0, min_p=0, repeat_penalty=1,
frequency_penalty=0, presence_penalty=0, dynatemp_range=0, mirostat=0,
samplers=["temperature"]`。固定 seed，自动追加最终分布采样。
P0 已核验服务端回显全部请求字段；不是只依据文档宣布支持。
原 B0 保留 temperature=0 及其原有省略字段，不能把服务器默认过滤器当成官方配置。

## 模板、提示与资源分别记录

`no_think` 属于渲染后的 Hy30 模板；任务、风格、上下文属于提示内容；
temperature／n_predict／grammar／cache_prompt 属于 HTTP 参数；context 与 KV 类型属于服务启动参数。
不能通过修改任务文字声称改变模型模板，也不能把总 context 当作输出预算。

[官方模板](https://huggingface.co/tencent/Hy-MT2-30B-A3B/blob/e0f86288a540bf477a4d7093fa624ee49f7a234f/chat_template.jinja)
存在 no_think／low／high 分支，但本轮实际模板仍为 no_think。
low／high 与 native completion、思考分离、GBNF 的组合尚未验证，不能称为可直接替换的能力。

本机 `e7-capacity-runtime/` 实测总 context8192、f16 KV、49/49 GPU 层，
分别设置 n_predict1024／4096，短窗两次均完成；最低空闲显存223MiB。
实际输出只有99tokens，故不能推导长输出、满context或长期运行稳定性。
模型 config 的位置上限也不能证明本机对应长度可用。

## 可追溯证据

本地根：`.local/translation-evaluation/hy30-flow-20261007/`。
`p0-runtime/`保存官方族回显；`p1-e1-t0-equivalence.json`保存温度0与B0的八窗逐字等价；
`e7-capacity-card.json`与`e7-capacity-runtime/`保存事前资源试验卡及实际loader／显存／响应。
官方模型仓库 main 页面会变化，模板使用固定文件提交；不得把这份核对当成所有未来版本的接口保证。
