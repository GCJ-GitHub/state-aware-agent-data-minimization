"""CPU-only trace audit/token accounting. Replays outputs; does not call a model."""

from publication import model_path
import json
from collections import defaultdict
from transformers import AutoTokenizer
import blind_three_arm as e


def main():
    e.verify()
    tokenizer = AutoTokenizer.from_pretrained(str(model_path()), local_files_only=True)
    cases = {c['id']:c for c in json.loads((e.ROOT/'tasks.json').read_text())}
    totals = defaultdict(lambda: defaultdict(int))
    details = []
    for line in (e.ROOT/'traces.jsonl').read_text().splitlines():
        row = json.loads(line)
        counter = 0
        inputs = []
        def replay(messages):
            nonlocal counter
            tokens = tokenizer.apply_chat_template(messages,tools=e.TOOLS,tokenize=True,
                         add_generation_prompt=True,enable_thinking=False,return_dict=False)
            inputs.append(len(tokens))
            raw = row['outputs'][counter]
            counter += 1
            return raw,len(tokenizer.encode(raw,add_special_tokens=False))
        reconstructed = e.run_episode(cases[row['id']],row['arm'],row['seed'],replay)
        for key in ('events','observations','terminal','attempted_routes','completed_routes','model_calls','tool_calls','confirmation_calls','recovery_prompts'):
            assert reconstructed[key] == row[key], (row['id'],row['arm'],row['seed'],key)
        total = totals[row['arm']]
        total['episodes'] += 1
        total['input_tokens'] += sum(inputs)
        total['output_tokens'] += reconstructed['output_tokens']
        total['model_calls'] += len(inputs)
        details.append({'id':row['id'],'arm':row['arm'],'seed':row['seed'],'input_tokens':sum(inputs),
                        'output_tokens':reconstructed['output_tokens']})
    e.dump(e.ROOT/'token-audit.json',{'totals':dict(totals),'details':details,
            'note':'CPU replay of exact stored model outputs and frozen backend; no new model inference. Full logical prompt token counts, before prefix caching.'})
    print('TRACE_REPLAY_OK',sum(v['episodes'] for v in totals.values()),dict(totals))


if __name__ == '__main__':
    main()
