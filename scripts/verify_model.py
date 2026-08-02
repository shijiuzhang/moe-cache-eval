from __future__ import annotations

import argparse
import platform
import time

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer


MODELS = {
    "granite": "ibm-granite/granite-3.1-3b-a800m-base",
    "olmoe": "allenai/OLMoE-1B-7B-0125",
}


def select_device() -> tuple[torch.device, torch.dtype]:
    if torch.backends.mps.is_available():
        return torch.device("mps"), torch.float16
    return torch.device("cpu"), torch.float32


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=MODELS)
    parser.add_argument("--local-files-only", action="store_true")
    args = parser.parse_args()

    model_id = MODELS[args.model]
    device, dtype = select_device()
    print(f"platform={platform.platform()}")
    print(f"torch={torch.__version__} transformers={transformers.__version__}")
    print(f"model={model_id} device={device} dtype={dtype}")

    tokenizer = AutoTokenizer.from_pretrained(
        model_id, local_files_only=args.local_files_only
    )
    started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        dtype=dtype,
        low_cpu_mem_usage=True,
        local_files_only=args.local_files_only,
    )
    model.to(device)
    model.eval()
    print(f"loaded_in={time.perf_counter() - started:.2f}s")

    text = (
        "A researcher has 17 samples and adds 8 more. "
        "Explain the operation and state the total."
    )
    inputs = tokenizer(text, return_tensors="pt")
    inputs = {name: tensor.to(device) for name, tensor in inputs.items()}

    with torch.inference_mode():
        outputs = model(
            **inputs,
            output_router_logits=True,
            use_cache=False,
            return_dict=True,
        )

    router_logits = outputs.router_logits
    if router_logits is None:
        raise RuntimeError("The model did not return router logits.")

    shapes = [tuple(layer.shape) for layer in router_logits]
    print(f"input_tokens={inputs['input_ids'].shape[-1]}")
    print(f"logits_shape={tuple(outputs.logits.shape)}")
    print(f"router_layers={len(router_logits)}")
    print(f"router_first_shape={shapes[0]}")
    print(f"router_last_shape={shapes[-1]}")
    print("status=OK")


if __name__ == "__main__":
    main()
