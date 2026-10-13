# Third-Party Notices

- `vendor/agent-jev/agentjev` and `vendor/agent-jev/jev_service` are the local,
  tested source snapshot originally acquired from
  <https://github.com/malevrigns/agent-jev>. The original Apache-2.0 license is
  preserved at `vendor/agent-jev/LICENSE`. No model tensors are redistributed.
  Only the required inference modules are included. File SHA-256 entries
  identify the packaged revision; it is not claimed to be the latest upstream.
- `web/lucide.min.js` is the existing Lucide browser icon distribution used by
  the project's earlier UI. Lucide is distributed under ISC; its notice is
  preserved separately at `web/LUCIDE-LICENSE.txt`.
- Cloud-OpsBench is referenced as an external runtime asset. Its snapshot
  loader and catalog are copied into an ignored run only when preparing a run.
  Original benchmark data, golden trajectories, process labels and source
  payloads are not included in this release package. Follow its MIT license
  when obtaining or redistributing upstream assets.
- The LLM is external, not packaged. Users must comply with the terms of Qwen
  and any selected replacement model.
- OpenSpiel provides the PUCT/MCTS implementation for the optional active-search
  experiment and is installed as an Apache-2.0 dependency, not vendored.
  scikit-learn provides the historical sparse experience estimator under BSD-3-Clause.
- OpsHarness and DeepSeek Harness are research/background references, not
  bundled dependencies or official endorsements.
- The original project's new research code has not been assigned a new
  blanket open-source license by this packaging operation. Choose one before
  public redistribution; keep third-party licenses and citations intact.

Final metrics and sanitized traces are retained only in the compressed frontend
presentation resource. Packaging is not a new full-benchmark experiment.
