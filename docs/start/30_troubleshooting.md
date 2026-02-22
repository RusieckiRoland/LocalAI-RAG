# Troubleshooting

* **`llama-cpp-python` runs on CPU**: You likely installed the CPU wheel. Reinstall a **CUDA** wheel matching your CUDA (e.g., `cu121`). Ensure `verbose=True` and check logs.
* **`nvidia-smi` not found in WSL**: Update WSL and Windows NVIDIA drivers; reboot and retry.
* **Weaviate BM25 `AND` timeouts (gRPC)**: On Weaviate `1.32.2` the gRPC BM25 operator `AND` can hang and end in `Deadline Exceeded`, even though the same BM25 query works via GraphQL. Upgrading Weaviate (e.g., `1.32.17` or newer) fixes the timeout. After upgrade, `AND` may still be overly strict and return `0` hits; consider falling back to `OR` or no operator when `AND` yields empty results.
