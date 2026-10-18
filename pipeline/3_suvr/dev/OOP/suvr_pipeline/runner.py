"""Run a stage's tasks across subjects, serially or over a process pool, and summarise."""
from __future__ import annotations

import logging
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Sequence

from tqdm import tqdm

from .layout import Subject
from .stages import Outcome, Stage, Status

log = logging.getLogger(__name__)


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )


def available_cores() -> int:
    return len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)


@dataclass
class StageRunner:
    cores: int = 1
    verbose: bool = False

    def collect(self, stage: Stage, subjects: Sequence[Subject]) -> List:
        tasks = []
        for subject in subjects:
            try:
                found = stage.tasks(subject)
            except Exception as e:
                log.error("[%s] %s: could not list tasks: %s", stage.name, subject.id, e)
                continue
            if not found:
                log.debug("[%s] %s: nothing to do", stage.name, subject.id)
            tasks.extend(found)
        return tasks

    def run(self, stage: Stage, subjects: Sequence[Subject]) -> List[Outcome]:
        tasks = self.collect(stage, subjects)
        workers = max(1, min(self.cores, available_cores(), len(tasks)))
        log.info("[%s] %d task(s) from %d subject(s), %d worker(s)", stage.name, len(tasks), len(subjects), workers)
        if not tasks:
            return []

        progress = dict(total=len(tasks), desc=stage.name, unit="task", disable=None)
        if workers == 1:
            outcomes = [stage.run(t) for t in tqdm(tasks, **progress)]
        else:
            outcomes = []
            with ProcessPoolExecutor(workers, initializer=configure_logging, initargs=(self.verbose,)) as pool:
                futures = [pool.submit(stage.run, t) for t in tasks]
                for future in tqdm(as_completed(futures), **progress):
                    outcomes.append(future.result())

        self.summarise(stage, outcomes)
        return outcomes

    @staticmethod
    def summarise(stage: Stage, outcomes: Sequence[Outcome]) -> None:
        counts = Counter(o.status for o in outcomes)
        log.info(
            "[%s] done %d, skipped %d, failed %d",
            stage.name, counts[Status.DONE], counts[Status.SKIPPED], counts[Status.FAILED],
        )
        for o in outcomes:
            if o.status is Status.FAILED:
                log.error("[%s] FAILED %s: %s", stage.name, o.label, o.message)
