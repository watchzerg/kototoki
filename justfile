set windows-shell := ["pwsh", "-NoLogo", "-NoProfile", "-Command"]

default:
    @just --list

# core 产品测试：只发现 tests/core/，-t . 使模块以 tests.core.* 导入；可追加 unittest 参数（如 -k 名称片段）定向运行。
# 目录为空时 unittest 报 NO TESTS RAN 并非零退出。
test *args:
    uv run --locked --offline python -m unittest discover -s tests/core -t . -v {{args}}

# 用默认配置为 DIR（相对路径按调用目录解析）下的视频与音频生成双语字幕：占 GPU、加载模型、可能跑数小时（须先问）。
# 只设 input_dir，其余取默认；要改其他键请写 kototoki.toml 并用 python -m kototoki（scripts/subtitles.py）。退出码同产品入口。
subtitles dir:
    uv run --locked --offline python scripts/subtitles.py '{{replace(join(invocation_directory_native(), dir), "'", "''")}}'; exit $LASTEXITCODE

check:
    uv run --locked --offline python -m compileall -q kototoki scripts tests

# --- Contract recipes (docs/development/workflow.md#命令与门禁) ---

# Verify uv/just versions (mise.toml) and Python (.python-version); never syncs or downloads.
check-toolchain:
    uv run --no-project --no-python-downloads --offline python scripts/check_toolchain.py

# 按 uv.lock 同步根环境（改环境、可能联网，须先问；ffmpeg、Strata 等外部前置由用户安装，docs/development/dependencies.md）。
install:
    uv sync --locked

# 按选版规则把 Python 依赖升到最新稳定版（联网、改环境，须先问；docs/development/dependencies.md#升级）。
# 随后跑 core、full 测试与资产核对，smoke 另行批准。
upgrade *args:
    uv run --no-project --no-python-downloads --offline python -X utf8 scripts/upgrade.py {{args}}
    just test
    just test-full
    just verify-assets

# 只报告可升级项，不改文件（联网查询 PyPI）。
upgrade-check *args:
    uv run --no-project --no-python-downloads --offline python -X utf8 scripts/upgrade.py --check {{args}}

# 按 assets.toml 下载缺失或不符的模型（几十 GB、联网，须先问；不并入 install）。
fetch-models:
    uv run --locked --offline python -X utf8 scripts/assets.py fetch-models

# 离线核对已下载的模型与 assets.toml 一致（size+mtime 缓存，不下载）。
verify-assets:
    uv run --locked --offline python -X utf8 scripts/assets.py verify

fmt *args:
    @echo "fmt: no formatter selected for this project (see docs/development/toolchain.md)" && exit 1

lint:
    @echo "lint: no linter selected; 'just check' is only a compile check (see docs/development/toolchain.md)" && exit 1

typecheck:
    @echo "typecheck: no type checker selected (see docs/development/toolchain.md)" && exit 1

# full 产品测试：离线集成（项目内 ffmpeg、fake worker），不加载模型、不占 GPU、不持锁；参数同 test。
test-full *args:
    uv run --locked --offline python -m unittest discover -s tests/full -t . -v {{args}}

# 真实模型验证（占 GPU、加载模型，每次须先经用户批准；不属于任何 gate）：每项独立子进程，持 .local/gpu.lock，
# 结果写 .local/smoke/；可只跑指定项。
smoke *args:
    uv run --locked --offline python scripts/smoke/run_all.py {{args}}

docs-check:
    uv run --locked --offline python scripts/check_docs.py

# lint、typecheck 未选定工具，不在门禁内；以编译检查 check 代替（docs/development/workflow.md#命令与门禁）。
gate-core: check-toolchain docs-check check test

gate-full: gate-core test-full
