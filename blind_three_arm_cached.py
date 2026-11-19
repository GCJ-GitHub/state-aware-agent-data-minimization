"""Memory-bounded serial adapter with exact-prefix cache reuse; frozen workflow."""

from publication import model_path
import hashlib
import json
import random
import time
from pathlib import Path
import blind_three_arm as e


def main():
    e.verify()
    import mlx.core as mx
    from mlx_lm import load, generate
    from mlx_lm.models.cache import make_prompt_cache, trim_prompt_cache
    from mlx_lm.sample_utils import make_sampler
    model, tokenizer = load(str(model_path()))
    sampler = make_sampler(temp=0.3)
    cache = make_prompt_cache(model)
    previous = []
    counts = []
    def infer(messages):
        nonlocal previous
        prompt = tokenizer.apply_chat_template(messages, tools=e.TOOLS, tokenize=True,
                    add_generation_prompt=True, enable_thinking=False)
        common = 0
        for a, b in zip(previous, prompt):
            if a != b:
                break
            common += 1
        common = min(common, len(prompt)-1)
        trim_prompt_cache(cache, cache[0].offset-common)
        raw = generate(model, tokenizer, prompt=prompt[common:], prompt_cache=cache,
                       sampler=sampler, max_tokens=192, prefill_step_size=256)
        # Retain only the known exact prompt prefix; no decoded-output assumptions.
        trim_prompt_cache(cache, cache[0].offset-len(prompt))
        previous = prompt
        counts.append((len(prompt), len(prompt)-common))
        return raw, len(tokenizer.encode(raw, add_special_tokens=False))
    path = e.ROOT/'traces.jsonl'
    done = {(r['id'],r['arm'],r['seed']) for line in path.read_text().splitlines()
            if (r:=json.loads(line))} if path.exists() else set()
    cases = json.loads((e.ROOT/'tasks.json').read_text())
    schedule = [(c,a,s) for s in e.SEEDS for c in cases for a in e.ARMS]
    random.Random(11773).shuffle(schedule)
    manifest = {'adapter': Path(__file__).name, 'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'at':time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'completed_before_adapter': len(done),
                'rule_changes':False, 'note':'Exact prompt prefix caching only; same frozen workflow, prompts, tools, limits, temperature, seeds and model. Batch engine stopped on GPU OOM; incomplete episodes excluded.'}
    e.dump(e.ROOT/'cached-adapter.json', manifest)
    started = time.perf_counter()
    with path.open('a') as f:
        for c,arm,seed in schedule:
            if (c['id'],arm,seed) in done:
                continue
            mx.random.seed(seed+int(hashlib.sha256(c['id'].encode()).hexdigest()[:6],16))
            counts.clear()
            row = e.run_episode(c,arm,seed,infer)
            row['engine'] = 'mlx_cached_serial'
            row['input_tokens'] = sum(a for a,b in counts)
            row['uncached_input_tokens'] = sum(b for a,b in counts)
            f.write(json.dumps(row,ensure_ascii=False)+'\n')
            f.flush()
            done.add((c['id'],arm,seed))
            print(len(done),'/1080',c['id'],arm,seed,'terminal',row['terminal'],
                  'tools',row['tool_calls'],'seconds',round(row['elapsed_s'],1),
                  'wall',round(time.perf_counter()-started,1),flush=True)
            mx.clear_cache()
    e.verify()
    e.summarize()


if __name__ == '__main__':
    main()
