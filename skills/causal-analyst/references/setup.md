# Setup

Tested with Python 3.11: numpy 2.4, pandas 3.0, scipy 1.15, scikit-learn 1.8, statsmodels 0.15,
econml 0.17, dowhy 0.14, matplotlib 3.10, pyarrow (for Parquet).

Check before the first run:

```bash
python -c "import numpy, pandas, scipy, sklearn, statsmodels, econml, dowhy, matplotlib; print('ok')"
```

If something is missing, tell the user what is missing and ask before installing
(`pip install econml dowhy statsmodels pyarrow`; add `--break-system-packages` on managed
system Pythons).

Troubleshooting:
- Very large files (>500k rows): use `budget: "quick"` or sample rows for a first pass and say so.
- `double_ml` / `causal_forest` errors: they are sensitivity checks; the run continues and the
  error is recorded in results.json. Mention it in Run details.
- Runtime: standard budget on 5k rows takes 30-60 seconds on an idle machine; causal forest and
  repeated cross-fitting dominate. The script pins numeric libraries to one thread because
  oversubscribed threads made shared machines 20-30x slower; set `OMP_NUM_THREADS` yourself to
  override. Run in the background and watch the log if tool calls time out.

## Optional: foundation-model cross-checks

**CausalPFN** (local; nothing leaves the machine): `pip install causalpfn` (pulls in PyTorch, CPU is
fine). Weights (`causalpfn_v0.pt`, 75 MB) download from Hugging Face on first use; if the network
blocks Hugging Face, download them manually and set `CAUSALPFN_WEIGHTS=/path/to/folder`. On Apple
Silicon, CausalPFN 0.1.4 can crash from two copies of the OpenMP runtime (faiss + torch); running the
script with `OMP_NUM_THREADS=1` (its default) avoids it. Skipped above `causalpfn_max_rows` (default
20,000) because it is slow on CPU.

**TabPFN** (hosted by Prior Labs; data IS sent to their API): `pip install tabpfn-client`, allow
`api.priorlabs.ai` in network settings, and provide a key via `TABPFN_TOKEN` or a file path in
`TABPFN_TOKEN_FILE` (never paste keys into chat). Runs only when the spec includes
`"allow_external_services": ["tabpfn_api"]`, which you set only after the SME agrees their data may
go to a third party.
