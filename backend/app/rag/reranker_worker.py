"""Separate process: local CPU weights only; no remote code or downloads."""

import json
import sys


def main():
    from sentence_transformers import CrossEncoder

    data = json.load(sys.stdin)
    model = CrossEncoder(
        data["model_path"],
        device="cpu",
        local_files_only=True,
        trust_remote_code=False,
        token=False,
    )
    pairs = [(data["query"], text) for text in data["documents"]]
    values = model.predict(pairs, batch_size=8, show_progress_bar=False)
    print(json.dumps([float(value) for value in values]))


if __name__ == "__main__":
    main()
