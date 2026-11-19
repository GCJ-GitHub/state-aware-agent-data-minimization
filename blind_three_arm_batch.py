"""Batch execution adapter: imports the frozen workflow without changing its rules."""

from publication import model_path
import concurrent.futures as cf
import hashlib
import json
import queue
import random
import time
from pathlib import Path

import blind_three_arm as experiment


def main():
    experiment.verify()
    import mlx.core as mx
    from mlx_lm import load
    from mlx_lm.generate import BatchGenerator
    from mlx_lm.models.cache import trim_prompt_cache
    root = experiment.ROOT
    model, tokenizer = load(str(model_path()))
    path = root/'traces.jsonl'
    done = {(r['id'], r['arm'], r['seed']) for line in path.read_text().splitlines()
            if (r := json.loads(line))} if path.exists() else set()
    cases = json.loads((root/'tasks.json').read_text())
    schedule = [(c, arm, seed) for seed in experiment.SEEDS for c in cases for arm in experiment.ARMS]
    random.Random(11773).shuffle(schedule)
    schedule = [(c, a, s) for c, a, s in schedule if (c['id'], a, s) not in done]
    requests = queue.Queue()
    # MLX operations all run in this main thread. Threads only manage independent
    # frozen business workflows, blocking on inference requests.
    def episode(c, arm, seed):
        input_counts = []
        def infer(messages):
            result = cf.Future()
            requests.put((messages, (c['id'], arm, seed), result))
            raw, tokens, n_input = result.result()
            input_counts.append(n_input)
            return raw, tokens
        row = experiment.run_episode(c, arm, seed, infer)
        row['input_tokens'] = sum(input_counts)
        row['engine'] = 'mlx_continuous_batch_adapter'
        return row

    sampler_states = {}
    prompt_states = {}
    def sampler_for(key):
        if key not in sampler_states:
            episode_seed = key[2] + int(hashlib.sha256(key[0].encode()).hexdigest()[:6], 16)
            state = [mx.random.key(episode_seed)]
            def sample(logprobs):
                # Same categorical temperature distribution; isolate the RNG
                # stream per episode so scheduling cannot mix random states.
                next_key, sample_key = mx.random.split(state[0])
                state[0] = next_key
                return mx.random.categorical(logprobs * (1.0 / 0.3), key=sample_key)
            sampler_states[key] = sample
        return sampler_states[key]

    adapter = {'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'existing_serial_episodes': len(done),
               'batch_size': 12, 'rule_changes': False,
               'note': 'Execution adapter only. Same frozen run_episode, model, tokenizer, prompts, tools, seeds, temperature, limits, backend and scorer. Batching may change floating point rounding; wall latency includes batch queueing and is not directly comparable with serial traces.'}
    experiment.dump(root/'batch-adapter.json', adapter)
    started = time.perf_counter()
    pool = cf.ThreadPoolExecutor(max_workers=12)
    with path.open('a') as out:
        futures = set()
        jobs = iter(schedule)
        def fill():
            while len(futures) < 12:
                job = next(jobs, None)
                if job is None:
                    break
                futures.add(pool.submit(episode, *job))
        fill()
        while futures:
            finished = [f for f in futures if f.done()]
            for future in finished:
                row = future.result()
                out.write(json.dumps(row, ensure_ascii=False)+'\n')
                out.flush()
                done.add((row['id'], row['arm'], row['seed']))
                futures.remove(future)
                prompt_states.pop((row['id'], row['arm'], row['seed']), None)
                print(len(done), '/1080', row['id'], row['arm'], row['seed'],
                      'terminal', row['terminal'], 'tools', row['tool_calls'],
                      'wall', round(time.perf_counter()-started, 1), flush=True)
            fill()
            if not futures:
                break
            batch = []
            try:
                batch.append(requests.get(timeout=0.05))
            except queue.Empty:
                continue
            # Allow all ready independent workflows to join this decode batch.
            deadline = time.perf_counter()+0.03
            while len(batch) < 12:
                try:
                    batch.append(requests.get(timeout=max(0.001, deadline-time.perf_counter())))
                except queue.Empty:
                    break
            prompts = [tokenizer.apply_chat_template(m, tools=experiment.TOOLS,
                        tokenize=True, add_generation_prompt=True, enable_thinking=False) for m, _, _ in batch]
            gen = BatchGenerator(model, max_tokens=192,
                                 stop_tokens=[[t] for t in tokenizer.eos_token_ids],
                                 completion_batch_size=12, prefill_batch_size=4, prefill_step_size=512)
            tails, caches, prefixes = [], [], []
            for prompt, (_, key, _) in zip(prompts, batch):
                cache, previous = prompt_states.get(key, (None, []))
                common = 0
                if cache:
                    for a, b in zip(previous, prompt):
                        if a != b:
                            break
                        common += 1
                    common = min(common, len(prompt)-1)
                    trim_prompt_cache(cache, len(previous)-common)
                tails.append(prompt[common:])
                caches.append(cache)
                prefixes.append(prompt[:common])
            uids = gen.insert(tails, caches=caches,
                              samplers=[sampler_for(key) for _, key, _ in batch])
            tokens = {uid: [] for uid in uids}
            new_states = {}
            try:
                while responses := gen.next_generated():
                    for response in responses:
                        if response.finish_reason != 'stop':
                            tokens[response.uid].append(response.token)
                        if response.finish_reason is not None:
                            new_states[response.uid] = (response.prompt_cache, response.all_tokens)
            finally:
                gen.close()
            for uid, prompt, prefix, (_, key, result) in zip(uids, prompts, prefixes, batch):
                cache, all_tokens = new_states[uid]
                prompt_states[key] = (cache, prefix + all_tokens)
                raw = tokenizer.decode(tokens[uid])
                result.set_result((raw, len(tokens[uid]), len(prompt)))
            print('BATCH', len(batch), 'new_prompt_tokens', sum(map(len, tails)),
                  'generated_tokens', sum(map(len, tokens.values())),
                  'wall', round(time.perf_counter()-started, 1), flush=True)
            mx.clear_cache()
    experiment.verify()
    experiment.summarize()
    pool.shutdown()


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        import os
        import traceback
        traceback.print_exc()
        import sys
        sys.stderr.flush()
        os._exit(1)
