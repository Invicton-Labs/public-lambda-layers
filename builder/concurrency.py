import concurrent
from collections.abc import Mapping

# Runs a function many times concurrently on a set of inputs
def concurrent_func(num_workers, worker_func, inputs: dict, expand_input=False):
    err = None
    results = {}
    max_workers = len(inputs)
    if num_workers is not None:
        max_workers = num_workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_input_key = {}
        for k, inpt in inputs.items():
            if expand_input:
                if isinstance(inpt, Mapping):
                    future = executor.submit(worker_func, **inpt)
                else:
                    future = executor.submit(worker_func, *inpt)
            else:
                future = executor.submit(worker_func, inpt)
            future_to_input_key[future] = k

        for future in concurrent.futures.as_completed(future_to_input_key):
            try:
                res = future.result()
                results[future_to_input_key[future]] = res
            except RuntimeError as e:
                err = e
                # If one job failed, exit all of them
                executor.shutdown(wait=True, cancel_futures=True)
                break
    if err is not None:
        raise err
    return results
