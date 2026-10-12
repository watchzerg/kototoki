set windows-shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

test:
    uv run --locked --offline python -m unittest discover -s tests -v
    uv run --locked --offline python -m unittest discover -s experiments/corpus -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/provision -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/whisper -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/japanese_ctc -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/qwen -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/crisp -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/display -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/analysis -t . -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/performance -t . -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/w0_demo -t . -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/x0_demo -t . -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/vad_comparison -t . -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/fullfilm_comparison -t . -p 'test_*.py' -v
    uv run --locked --offline python -m unittest discover -s experiments/asr_candidates -t . -p 'test_*.py' -v

x0-demo *args:
    uv run --locked --offline python -m experiments.x0_demo.run {{args}}

translation-test:
    uv run --locked --offline python -m unittest experiments.translation_demo.test_demo experiments.translation_eval.test_runner experiments.translation_judge.test_runner experiments.translation_judge.test_subagents experiments.translation_compat.test_compat tests.test_translation_comparison_report -v
    uv run --locked --offline python -m unittest tests.test_translation_corpus tests.test_translation_reference_judge tests.test_translation_monitor tests.test_translation_four_quantization tests.test_translation_four_stats tests.test_translation_four_performance tests.test_translation_identical_output_diagnostics tests.test_translation_terminology_diagnostics tests.test_translation_judge_integrity tests.test_translation_judge_scheduling -v

translation-demo *args:
    uv run --locked --offline python -m experiments.translation_demo_runtime {{args}}

# Adopted translation baseline; use translation-demo for explicit controls.
translation-baseline *args:
    uv run --locked --offline python -X utf8 -m experiments.translation_demo_runtime {{args}} --candidate hy-mt2-30b-a3b-apex-i-compact --engine '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/llama-server.exe' --engine-identity '.local/translation-evaluation/20261006-v1/hy30-compat/runtime/identity.json' --layers 99 --sampling-profile official30b-cached-v1 --n-predict 4096 --context-size 8192 --threads 8 --threads-batch 8

# Adopted full-SRT flow baseline (ADR-0006): APEX + official30b-cached-v1 + v3 recipe b10-joint. GPU.
translation-srt *args:
    uv run --locked --offline python -X utf8 -m experiments.translation_v3 translate-srt --recipe b10-joint {{args}}

translation-eval *args:
    uv run --locked --offline python -m experiments.translation_eval {{args}}

translation-flow *args:
    uv run --locked --offline python -m experiments.translation_flow {{args}}

translation-flow-test:
    uv run --locked --offline python -m unittest experiments.translation_flow.test_srt experiments.translation_flow.test_worker experiments.translation_flow.test_cli experiments.translation_flow.test_costs experiments.translation_flow.test_judge_loop experiments.translation_flow.test_project_evaluation experiments.translation_flow.test_screening experiments.translation_flow.test_dispatch experiments.translation_eval.test_runner -v

translation-flow-v2-test:
    uv run --locked --offline python -m unittest experiments.translation_flow.test_v2_prepare experiments.translation_flow.test_v2_common_source experiments.translation_flow.test_v2_common_diagnostics experiments.translation_flow.test_v2_output_budget experiments.translation_flow.test_v2_ordered_text experiments.translation_flow.test_combined_stage experiments.translation_flow.test_v2_prepare_integrity experiments.translation_flow.test_v2_worker experiments.translation_flow.test_v2_semantic experiments.translation_flow.test_v2_delivery experiments.translation_flow.test_v2_reproject experiments.translation_flow.test_v2_statistics experiments.translation_flow.test_v2_timing experiments.translation_flow.test_v2_evaluation experiments.translation_flow.test_v2_trial experiments.translation_flow.test_v2_confirmation experiments.translation_flow.test_v2_confirmation_dispatch experiments.translation_flow.test_v2_confirmation_evaluation tests.test_translation_flow_v2_source tests.test_translation_flow_v2_reference tests.test_translation_flow_v2_qualified tests.test_translation_flow_v2_id_text tests.test_translation_flow_v2_semantic_anchors tests.test_translation_flow_v2_source_preparation tests.test_translation_flow_v2_source_integration tests.test_translation_flow_v3_source_integration tests.test_translation_flow_v2_source_trial tests.test_translation_flow_v2_compare tests.test_translation_flow_v2_semantic_structured tests.test_translation_flow_v2_fluency experiments.translation_flow.test_v2_universal_review experiments.translation_flow.test_v2_matched_evaluation experiments.translation_flow.test_v2_fluency_runner experiments.translation_flow.test_v2_consistency experiments.translation_flow.test_v2_consistency_custody experiments.translation_flow.test_v2_consistency_runner tests.test_translation_flow_v2_consistency_prompt_contract tests.test_translation_flow_v2_consistency_pair_bridge tests.test_translation_flow_v2_consistency_bridge_runner experiments.translation_flow.test_v2_unit_diagnostics experiments.translation_flow.test_v2_unit_custody experiments.translation_flow.test_v2_unit_main_proof tests.test_translation_flow_v2_unit_main_proof_singleton tests.test_translation_flow_v2_unit_main_proof_partial tests.test_translation_flow_v2_unit_runner tests.test_translation_flow_v2_unit_role_seed_validator_partial tests.test_translation_flow_v2_unit_runner_partial tests.test_translation_flow_v2_review_diagnostics tests.test_translation_flow_v2_review_trigger_features tests.test_translation_flow_v2_review_root_evidence tests.test_translation_flow_v2_review_root_runner experiments.translation_flow.test_v2_review_evaluation experiments.translation_flow.test_v2_judge_dispatch experiments.translation_flow.test_v2_risk_reconciliation experiments.translation_flow.test_v2_risk_runner experiments.translation_flow.test_v2_risk_transport_runner tests.test_translation_flow_v2_semantic_partition_grammar tests.test_translation_flow_v2_source_proposals tests.test_translation_flow_v2_scene_card tests.test_translation_judge_integrity -v

check:
    uv run --locked --offline python -m compileall -q kototoki_eval experiments

setup:
    uv sync --locked
