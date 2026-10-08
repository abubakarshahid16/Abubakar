"""Chat redesign PR 7: the benchmark kit keeps client text in .cowork/."""
from __future__ import annotations

from ._base import REPO, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1017", phase=87, description='the kit writes client answers outside .cowork',
             path=REPO / "scripts" / "chat_benchmark.py",
             anchor='    if COWORK.resolve() not in resolved.parents:\n',
             replacement='    if False:\n',
             target='tests/test_chat_benchmark_script.py', keyword='outside_cowork', tags=("privacy",)),
    Mutation(id="M1018", phase=87, description='the kit writes a report git would track',
             path=REPO / "scripts" / "chat_benchmark.py",
             anchor='    if not git_ignores(report):\n',
             replacement='    if False:\n',
             target='tests/test_chat_benchmark_script.py', keyword='git_would_track', tags=("privacy",)),
    Mutation(id="M1019", phase=87, description='the kit prints each question as it runs',
             path=REPO / "scripts" / "chat_benchmark.py",
             anchor='        print(f"[{n}/{len(questions)}] {category}", flush=True)   # never the question text\n',
             replacement='        print(f"[{n}/{len(questions)}] {category} {question}", flush=True)\n',
             target='tests/test_chat_benchmark_script.py', keyword='leaves_scores_blank', tags=("privacy",)),
    Mutation(id="M1020", phase=87, description='one failed question loses the rest of the run',
             path=REPO / "scripts" / "chat_benchmark.py",
             anchor='        except Exception as exc:  # noqa: BLE001 - one failed question must not lose the rest\n            rows.append(row_of(n, category, question, None, str(exc)[:300]))\n',
             replacement='        except KeyError:\n            pass\n',
             target='tests/test_chat_benchmark_script.py', keyword='reported_not_lost', tags=("privacy",)),
)
