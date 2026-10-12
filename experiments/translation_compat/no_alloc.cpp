#include "llama.h"
#include "ggml-backend.h"

#include <cstdio>

int main(int argc, char ** argv) {
    if (argc != 3) {
        std::fprintf(stderr, "usage: no_alloc <cpu-backend-dll> <gguf>\n");
        return 2;
    }
    // Explicitly load only CPU metadata support; never discover CUDA or infer.
    if (ggml_backend_load(argv[1]) == nullptr) {
        return 3;
    }
    auto params = llama_model_default_params();
    params.n_gpu_layers = 0;
    params.no_alloc = true;
    params.load_mode = LLAMA_LOAD_MODE_NONE;
    auto * model = llama_model_load_from_file(argv[2], params);
    if (model == nullptr) {
        return 1;
    }
    std::printf("PASS: metadata and all tensor descriptors loaded without allocation or inference\n");
    llama_model_free(model);
    return 0;
}
