# llama.cpp CPU protocol qualification fixture

This fixture exercises the released OICAP measurement path against a real
OpenAI-compatible `llama.cpp` server for `V02-AC05`. It is a protocol
qualification workload, not a capacity benchmark and not a portable performance
baseline.

The checked environment used `llama-server` 10210 (`000547513`), CPU-only, and a
locally held 11.9B-parameter Q4_K_M GGUF whose SHA-256 is recorded in `sut.yaml`.
Another operator may substitute a local model, but must update `sut.yaml` and must
not compare resulting performance numbers across different SUT contracts.

With a server listening on port 18080:

```console
oicap validate examples/oicap/llama_cpp_ac05
oicap calibrate examples/oicap/llama_cpp_ac05 --output calibration
oicap run examples/oicap/llama_cpp_ac05 \
  --endpoint http://127.0.0.1:18080/v1/chat/completions \
  --calibration calibration --output run
oicap verify run --calibration-source calibration
python scripts/oicap_ac05_probe.py \
  --endpoint http://127.0.0.1:18080/v1/chat/completions \
  --output protocol-qualification.json
```

The workload deliberately includes one reasoning-enabled request and one
reasoning-disabled multi-content-chunk request. Hidden reasoning text is never
stored. Aggregate server usage remains usable for throughput accounting, but it
does not provide authoritative first-to-last token timing; therefore ITL and TPOT
remain unavailable for this real endpoint.
