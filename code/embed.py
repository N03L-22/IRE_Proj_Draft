"""T1d: frozen multilingual MiniLM embeddings of the article text of each store (one forward pass, no training).

Model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (as in Assignment 1), mean-pooled over the
attention mask, L2-normalised, fp16 on CUDA, 128 tokens, batches sorted by length. Weights come from the local
Hugging Face cache only. The output is data from here on: float32 (n, 384), rows in article-id order.
Run (torch lives in the user site, so not -I):  python -P embed.py <root> ebnerd npr adressa
"""
import hashlib, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import polars as pl

import monitor as M

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIM, MAX_TOKENS, BATCH = 384, 128, 128


def encode(texts, device):
    import torch
    from transformers import AutoModel, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    model = AutoModel.from_pretrained(MODEL, local_files_only=True).eval().to(device)
    if device == "cuda":
        model.half()
    out = np.empty((len(texts), DIM), dtype=np.float32)
    order = sorted(range(len(texts)), key=lambda i: (len(texts[i]), i))      # ties broken by index: fixed order
    with torch.inference_mode():
        for k in range(0, len(order), BATCH):
            rows = order[k:k + BATCH]
            enc = tok([texts[i] for i in rows], padding=True, truncation=True, max_length=MAX_TOKENS, return_tensors="pt")
            enc = {a: b.to(device) for a, b in enc.items()}
            h = model(**enc).last_hidden_state
            m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
            pooled = ((h * m).sum(1) / m.sum(1).clamp(min=1e-9)).float().cpu().numpy()
            out[rows] = pooled
    n = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(n, 1e-12)


def run(root, name):
    st = os.path.join(root, f"data/{name}/store")
    a = pl.read_parquet(os.path.join(st, "articles.parquet"), columns=["article", "text"]).sort("article")
    texts = [t if t else " " for t in a["text"].to_list()]
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    with M.Unit("t1d", name, trace_dir=os.path.join(st, "trace"), manifest=os.path.join(st, "manifest_t1d.jsonl"),
                rss_cap_gb=8, disk_dir=st) as u:
        with u.phase("encode"):
            t = time.time()
            V = encode(texts, device)
            secs = time.time() - t
        M.check_finite(V, "embeddings")
        norms = np.linalg.norm(V, axis=1)
        assert V.shape == (a.height, DIM)
        assert np.abs(norms - 1).max() < 1e-3, "not unit norm"
        # determinism: re-encode a fixed sample and compare
        idx = np.arange(0, a.height, max(1, a.height // 1000))[:1000]
        V2 = encode([texts[i] for i in idx], device)
        cos = (V[idx] * V2).sum(1)
        assert cos.min() > 0.999, f"re-encode differs: min cosine {cos.min()}"
        with u.phase("write"):
            M.atomic_write(os.path.join(st, "emb_minilm.npy"), lambda p: np.save(open(p, "wb"), V))
            M.atomic_write(os.path.join(st, "emb_ids.npy"), lambda p: np.save(open(p, "wb"), a["article"].to_numpy()))
        u.extra.update(articles=a.height, device=device, articles_per_s=round(a.height / secs), min_resample_cosine=float(cos.min()),
                       sha256=M.file_sha256(os.path.join(st, "emb_minilm.npy")))
    print(name, json.dumps(u.row))


if __name__ == "__main__":
    for n in sys.argv[2:]:
        run(sys.argv[1], n)
