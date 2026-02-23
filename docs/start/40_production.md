# Notes for production

* Use a **production WSGI server** (e.g., Gunicorn/uWSGI) instead of the Flask dev server (`flask run`). Disable debug, load environment variables via `python-dotenv` if needed, and place a reverse proxy (Nginx/Traefik) in front for TLS and compression.
* **Model integrity (checksums):** always verify the SHA‑256 of downloaded weights before startup.

  ```bash
  # Generate checksums after download (commit this file to the repo if you want reproducibility)
  (cd models/code_analysis/qwenCoder && sha256sum *.gguf > CHECKSUMS.sha256)
  (cd models/embedding/e5-base-v2 && find . -type f ! -name 'download_model.md' -print0 | xargs -0 sha256sum > CHECKSUMS.sha256)
  (cd models/translation/en_pl/Helsinki_NLPopus_mt_en_pl && sha256sum * > CHECKSUMS.sha256)
  (cd models/translation/pl_en/Helsinki_NLPopus_mt_pl_en && sha256sum * > CHECKSUMS.sha256)

  # Verify at deploy/start time
  sha256sum -c models/code_analysis/qwenCoder/CHECKSUMS.sha256
  sha256sum -c models/embedding/e5-base-v2/CHECKSUMS.sha256
  sha256sum -c models/translation/en_pl/Helsinki_NLPopus_mt_en_pl/CHECKSUMS.sha256
  sha256sum -c models/translation/pl_en/Helsinki_NLPopus_mt_pl_en/CHECKSUMS.sha256
  ```

  If you prefer, store expected digests in `checksums.json` and verify them in an app startup hook.
* **Deployment hygiene (remove MD placeholders):** production artifacts/images should ship only the code and the weights. Remove the `download_model.md` files during packaging to avoid leaking internal instructions:

  ```bash
  find models/code_analysis models/embedding models/translation -name 'download_model.md' -delete
  ```
* **GPU concurrency:** for a single GPU, prefer **one process/worker** to avoid loading the model multiple times into VRAM; scale with a queue or per‑GPU processes when needed.
* **Observability:** expose `/healthz` and `/readyz`, emit structured logs (JSON), and add latency/throughput metrics for retrieval and generation stages.
