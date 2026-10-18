set windows-shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]

# 冻结的 experiments recipe 在历史根环境（Python 3.12、无依赖）中运行，保持原有跳过行为与运行身份；
# 产品根环境（Torch 等）不用于它们（docs/development/workflow.md#测试分层与资源边界）。
legacy := "uv run --no-project --no-python-downloads --offline --python 3.12"

default:
    @just --list

# 产品测试：只发现 tests/，-t . 使模块以 tests.* 导入；tests/ 为空时 unittest 报 NO TESTS RAN 并非零退出。
test:
    uv run --locked --offline python -m unittest discover -s tests -t . -v

# 研究期离线测试，只读保留，不属于 gate-core（docs/development/workflow.md#测试分层与资源边界）。
experiments-test:
    {{legacy}} python -m unittest discover -s experiments/tests -t . -v
    {{legacy}} python -m unittest discover -s experiments/corpus -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/provision -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/whisper -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/japanese_ctc -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/qwen -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/crisp -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/display -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/analysis -t . -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/performance -t . -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/w0_demo -t . -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/x0_demo -t . -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/vad_comparison -t . -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/fullfilm_comparison -t . -p 'test_*.py' -v
    {{legacy}} python -m unittest discover -s experiments/asr_candidates -t . -p 'test_*.py' -v

x0-demo *args:
    {{legacy}} python -m experiments.x0_demo.run {{args}}

translation-test:
    {{legacy}} python -m unittest experiments.translation_demo.test_demo experiments.translation_eval.test_runner experiments.translation_judge.test_runner experiments.translation_judge.test_subagents experiments.translation_compat.test_compat -v

translation-demo *args:
    {{legacy}} python -m experiments.translation_demo_runtime {{args}}

# 历史记录：ADR-0005 的翻译基线入口，使用 b11429 兼容引擎；产品改用官方 b11583（ADR-0007），本 recipe 只供复现。
translation-baseline *args:
    {{legacy}} python -X utf8 -m experiments.translation_demo_runtime {{args}} --candidate hy-mt2-30b-a3b-apex-i-compact --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' --layers 99 --sampling-profile official30b-cached-v1 --n-predict 4096 --context-size 8192 --threads 8 --threads-batch 8

# Adopted full-SRT flow baseline (ADR-0010): APEX + official30b-cached-v1 + v3 recipe dp10-cut. GPU.
translation-srt *args:
    {{legacy}} python -X utf8 -m experiments.translation_v3 translate-srt --recipe dp10-cut {{args}}

translation-eval *args:
    {{legacy}} python -m experiments.translation_eval {{args}}

translation-flow *args:
    {{legacy}} python -m experiments.translation_flow {{args}}

translation-flow-test:
    {{legacy}} python -m unittest experiments.translation_flow.test_srt experiments.translation_flow.test_worker experiments.translation_flow.test_cli experiments.translation_flow.test_costs experiments.translation_flow.test_judge_loop experiments.translation_flow.test_project_evaluation experiments.translation_flow.test_screening experiments.translation_flow.test_dispatch experiments.translation_eval.test_runner -v

# 冻结的 test_v2_common_diagnostics、test_v2_confirmation_evaluation 仍从旧的 tests 位置导入，原样保留、不再列入。
translation-flow-v2-test:
    {{legacy}} python -m unittest experiments.translation_flow.test_v2_prepare experiments.translation_flow.test_v2_common_source experiments.translation_flow.test_v2_output_budget experiments.translation_flow.test_v2_ordered_text experiments.translation_flow.test_combined_stage experiments.translation_flow.test_v2_prepare_integrity experiments.translation_flow.test_v2_worker experiments.translation_flow.test_v2_semantic experiments.translation_flow.test_v2_delivery experiments.translation_flow.test_v2_reproject experiments.translation_flow.test_v2_statistics experiments.translation_flow.test_v2_timing experiments.translation_flow.test_v2_evaluation experiments.translation_flow.test_v2_trial experiments.translation_flow.test_v2_confirmation experiments.translation_flow.test_v2_confirmation_dispatch experiments.translation_flow.test_v2_universal_review experiments.translation_flow.test_v2_matched_evaluation experiments.translation_flow.test_v2_fluency_runner experiments.translation_flow.test_v2_consistency experiments.translation_flow.test_v2_consistency_custody experiments.translation_flow.test_v2_consistency_runner experiments.translation_flow.test_v2_unit_diagnostics experiments.translation_flow.test_v2_unit_custody experiments.translation_flow.test_v2_unit_main_proof experiments.translation_flow.test_v2_review_evaluation experiments.translation_flow.test_v2_judge_dispatch experiments.translation_flow.test_v2_risk_reconciliation experiments.translation_flow.test_v2_risk_runner experiments.translation_flow.test_v2_risk_transport_runner -v

check:
    uv run --locked --offline python -m compileall -q kototoki kototoki_eval experiments

setup:
    uv sync --locked

# --- Contract recipes (docs/development/workflow.md#命令与门禁) ---

# Verify uv/just versions (mise.toml) and Python (.python-version); never syncs or downloads.
check-toolchain:
    uv run --no-project --no-python-downloads --offline python scripts/check_toolchain.py

# Install the root environment from uv.lock (same as setup; changes the environment, ask first).
install: setup

fmt *args:
    @echo "fmt: no formatter selected for this project (see docs/development/toolchain.md)" && exit 1

lint:
    @echo "lint: no linter selected; 'just check' is only a compile check (see docs/development/toolchain.md)" && exit 1

typecheck:
    @echo "typecheck: no type checker selected (see docs/development/toolchain.md)" && exit 1

# 环境 smoke（占 GPU、加载模型，须先经用户批准）：每项独立子进程，结果写 .local/smoke/；可只跑指定项。
test-full *args:
    uv run --locked --offline python scripts/smoke/run_all.py {{args}}

docs-check:
    uv run --locked --offline python scripts/check_docs.py

gate-core: check-toolchain docs-check lint typecheck test

gate-full: gate-core test-full
