"""LoRA fine-tune of Llama 3.2 1B Instruct on data/train.jsonl (prompt-completion; loss on the answer only),
then merge the adapter into a standalone model for vLLM.

  python llm/train_lora.py --base <Llama-3.2-1B-Instruct path> --out <dir> [--epochs 2]
  torchrun --nproc_per_node 8 llm/train_lora.py ...      (one process per GPU)
"""
import argparse
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--bs", type=int, default=8, help="per-GPU batch; accumulation keeps 16 per GPU step")
    ap.add_argument("--no-gc", action="store_true", help="no gradient checkpointing: faster, more memory")
    a = ap.parse_args()
    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(a.base)
    tok.pad_token = tok.pad_token or "<|finetune_right_pad_id|>"
    ds = load_dataset("json", data_files={"train": str(HERE / "data" / "train.jsonl"),
                                          "eval": str(HERE / "data" / "eval.jsonl")})
    ds = ds.remove_columns([c for c in ds["train"].column_names if c not in ("prompt", "completion")])
    model = AutoModelForCausalLM.from_pretrained(a.base, dtype=torch.bfloat16, attn_implementation="sdpa")
    out = Path(a.out)
    world = int(os.environ.get("WORLD_SIZE", "1"))
    cfg = SFTConfig(output_dir=str(out / "ckpt"), num_train_epochs=a.epochs, learning_rate=a.lr,
                    per_device_train_batch_size=a.bs, gradient_accumulation_steps=max(1, 16 // (a.bs * world)), per_device_eval_batch_size=8,
                    lr_scheduler_type="cosine", warmup_steps=20, bf16=True, logging_steps=20,
                    eval_strategy="steps", eval_steps=100, save_strategy="no", max_length=3072,
                    gradient_checkpointing=not a.no_gc, report_to=[], completion_only_loss=True)
    lora = LoraConfig(r=64, lora_alpha=128, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
    tr = SFTTrainer(model=model, args=cfg, train_dataset=ds["train"], eval_dataset=ds["eval"],
                    processing_class=tok, peft_config=lora)
    tr.train()
    print("final eval", tr.evaluate())
    if not tr.is_world_process_zero():
        return
    merged = tr.model.merge_and_unload()
    merged.save_pretrained(out / "merged", safe_serialization=True)
    tok.save_pretrained(out / "merged")
    for f in ("LICENSE.txt", "USE_POLICY.md"):            # the Llama licence travels with the weights
        src = Path(a.base) / f
        if src.exists():
            (out / "merged" / f).write_bytes(src.read_bytes())
    print("saved", out / "merged")


if __name__ == "__main__":
    main()
