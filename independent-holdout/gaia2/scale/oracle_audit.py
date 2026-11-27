"""Mechanically replay the upstream oracle graph without querying a language model."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from pathlib import Path
import sys

from run import core, read_cases


class NoInference:
    def __call__(self, *args, **kwargs):
        raise AssertionError("Oracle replay does not need a model")


def verify(item):
    case_id, case = item
    try:
        scenario, _, _ = core.JsonScenarioImporter().import_from_json_to_benchmark(
            case["raw"], load_completed_events=False
        )
        core.preprocess_scenario(scenario, judge_config=core.GraphPerEventJudgeConfig(engine=NoInference()))
        observed = {
            event.event_id for event in scenario.oracle_run_event_log
            if event.event_type == core.EventType.ENV and not event.failed()
        }
        expected = set(case["original_event_ids"])
        return {
            "case": case_id,
            "planned_events": len(expected),
            "observed_events": len(expected & observed),
            "all_events_replayed": expected <= observed,
        }
    except Exception as error:
        return {
            "case": case_id,
            "planned_events": len(case["original_event_ids"]),
            "exception_type": type(error).__name__,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    cases = read_cases(Path(sys.argv[1]))
    with Path(sys.argv[2]).open("w", buffering=1) as output:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(verify, item) for item in cases.items()]
            for future in as_completed(futures):
                output.write(json.dumps(future.result()) + "\n")
