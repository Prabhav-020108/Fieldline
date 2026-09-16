"""
Phase 7f: offline retrieval/answer-quality evaluation harness, using Ragas
against a small, hand-written golden set covering four of FieldLine's five
tools (log_job_note is a write, not a retrieval-quality question, so it's
not part of this harness).

CRITICAL DESIGN POINT: this is a standalone BATCH script. It never runs
inline with a real technician's call -- scoring every real interaction
with an LLM judge would add multi-second latency and directly undercut
the product's zero-latency pitch. Run this by hand, or wire it into CI,
but never from agent.py or any tools/*.py file.

Usage (from the agent/ folder):

    uv sync --group eval
    uv run --group eval python eval/run_ragas_eval.py

This uses Groq (the same free-tier provider already configured for the
live agent, via GROQ_API_KEY in .env.local) as the LLM judge, through
Ragas' LangChain wrapper -- so this eval never needs a separate paid
OpenAI key.

Tracing is intentionally disabled for this script (see the
OTEL_SDK_DISABLED line right below the imports): this harness scores
answer/context quality against a golden set, not live-call latency, so
there's no reason to require a running Phoenix instance just to run it,
and no reason to spam retry warnings if one isn't running. Live calls
through agent.py are still fully traced as normal -- this only affects
this one script.

NOTE ON RAGAS/LANGCHAIN VERSION DRIFT: `ragas`'s base module has a habit
of unconditionally importing several *optional* LangChain provider
integrations (Vertex AI, Bedrock, etc.) purely for its own internal
provider-auto-detection logic -- even though this script only ever uses
Groq via an OpenAI-compatible client. Depending on which langchain-
community version your resolver picks, one or more of those optional
submodules may not exist (LangChain has been migrating provider
integrations out of langchain-community into separate partner packages),
which crashes the bare `from ragas import evaluate` import with a
ModuleNotFoundError that has nothing to do with anything this script
actually uses. _ensure_optional_langchain_integrations_importable() below
pre-registers harmless stubs for the known-troublesome ones, ONLY if the
real module isn't already importable, so this script keeps working across
`uv sync` upgrades without needing exact version pins. If you ever see a
NEW ModuleNotFoundError for a *different* langchain_community provider
path than the ones listed below, add it to the `optional_integrations`
list the same way -- don't chase version pins instead.
"""

import asyncio
import os
import sys

# Belt-and-suspenders: the editable install from `uv sync` should already
# put src/ on sys.path (the same way agent/tests/*.py import `tools.*` and
# `moss_client` directly), but this makes the script resilient even if
# it's ever run from an environment where that didn't happen.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.join(_THIS_DIR, "..", "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

# Must be set BEFORE importing anything under tools/*.py -- those modules
# import tracing.py, which builds its OpenTelemetry tracer at import time.
# setdefault() means this only applies if the shell environment hasn't
# already set OTEL_SDK_DISABLED itself, so you can still override it
# (e.g. `$env:OTEL_SDK_DISABLED = "false"`) if you deliberately want to
# see eval-run retrieval spans in a running Phoenix instance.
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_THIS_DIR, "..", ".env.local"))  # noqa: E402

import company_context  # noqa: E402
from moss import QueryOptions  # noqa: E402
from moss_client import get_index  # noqa: E402
from tools.dispatch_status import dispatch_status  # noqa: E402
from tools.fault_history import fault_history  # noqa: E402
from tools.inventory_lookup import inventory_lookup  # noqa: E402
from tools.safety_procedure import safety_procedure  # noqa: E402

company_context.set_current_company("site-demo")

# ---------------------------------------------------------------------------
# Golden set -- extend this as you find real technician questions worth
# locking in as regression cases.
# ---------------------------------------------------------------------------

EVAL_QUERIES = [
    {
        "tool": "safety_procedure",
        "question": "What's the lockout procedure for panel B?",
        "kwargs": {"topic": "panel B lockout"},
        "raw_query": "panel B lockout",
        "filter_type": "safety_manual",
        "ground_truth": (
            "Notify affected personnel, shut down normally, isolate the "
            "energy source, apply lock and tag, release stored energy, "
            "then verify zero energy with a meter before starting work."
        ),
    },
    {
        "tool": "fault_history",
        "question": "What's the fault history on unit 12?",
        "kwargs": {"equipment_id": "unit-12"},
        "raw_query": "job and fault history for unit-12",
        "filter_type": "job_history",
        "ground_truth": (
            "Unit 12 had an overload trip on the 8th that was reset and "
            "monitored, and has an open recurring low-refrigerant flag "
            "from the 15th with a top-up scheduled."
        ),
    },
    {
        "tool": "inventory_lookup",
        "question": "Where's the LC1D18 contactor stored?",
        "kwargs": {"part_number": "LC1D18"},
        "raw_query": "inventory location for LC1D18",
        "filter_type": "inventory",
        "ground_truth": "Bin 14C in the site store room, quantity 3.",
    },
    {
        "tool": "dispatch_status",
        "question": "What's next on my job queue?",
        "kwargs": {},
        "raw_query": "current job queue dispatch status and reroutes",
        "filter_type": "dispatch_status",
        "ground_truth": (
            "One open job on unit-12 for the refrigerant top-up; "
            "everything else is closed."
        ),
    },
]

TOOL_FUNCTIONS = {
    "safety_procedure": safety_procedure,
    "fault_history": fault_history,
    "inventory_lookup": inventory_lookup,
    "dispatch_status": dispatch_status,
}


async def _fetch_raw_context(item: dict) -> list:
    """Queries Moss directly, separate from the tool's own answer text, so
    Ragas gets the actual retrieved passages as `contexts` -- this is what
    makes faithfulness/context_precision a meaningful check rather than the
    tool trivially "citing itself.\""""
    client, index_name = await get_index()
    results = await client.query(
        index_name,
        item["raw_query"],
        QueryOptions(
            top_k=5,
            alpha=0.4,
            filter={"field": "type", "condition": {"$eq": item["filter_type"]}},
        ),
    )
    return [doc.text for doc in results.docs] or ["(no matching documents found)"]


async def build_ragas_rows() -> list:
    rows = []
    for item in EVAL_QUERIES:
        tool_fn = TOOL_FUNCTIONS[item["tool"]]
        answer = await tool_fn(context=None, **item["kwargs"])
        contexts = await _fetch_raw_context(item)
        rows.append(
            {
                "question": item["question"],
                "answer": answer,
                "contexts": contexts,
                "ground_truth": item["ground_truth"],
            }
        )
    return rows


def _ensure_optional_langchain_integrations_importable() -> None:
    """
    Ragas' base module imports several optional LangChain provider
    integrations at load time purely for its own internal provider-
    auto-detection logic, even though this script only ever instantiates
    Groq via an OpenAI-compatible client. If your resolved
    langchain-community version is missing one of these submodules
    (common after a LangChain provider-integration migration), the bare
    `from ragas import evaluate` import below crashes with a
    ModuleNotFoundError unrelated to anything this script does.

    This pre-registers a harmless stub module for each KNOWN-troublesome
    optional path, but ONLY if the real module can't be imported -- so it
    never shadows a real, working integration, and costs nothing when
    your environment happens to have them all.
    """
    import importlib
    import types

    # (module path, class names that module is expected to export)
    optional_integrations = [
        ("langchain_community.chat_models.vertexai", ["ChatVertexAI"]),
        ("langchain_community.chat_models.bedrock", ["BedrockChat"]),
        ("langchain_community.llms.vertexai", ["VertexAI"]),
        ("langchain_community.llms.bedrock", ["Bedrock"]),
    ]

    for module_path, class_names in optional_integrations:
        try:
            importlib.import_module(module_path)
            continue  # real module is importable -- leave it alone
        except ImportError:
            pass

        stub = types.ModuleType(module_path)

        def _make_stub_class(name: str, path: str):
            class _StubUnused:  # pragma: no cover - never meant to be instantiated
                def __init__(self, *args, **kwargs):
                    raise RuntimeError(
                        f"{path}.{name} is a stub inserted by "
                        "run_ragas_eval.py because the real integration "
                        "isn't installed. FieldLine's eval harness only "
                        "uses Groq -- seeing this error means something "
                        "unexpectedly tried to use a different provider."
                    )

            _StubUnused.__name__ = name
            return _StubUnused

        for class_name in class_names:
            setattr(stub, class_name, _make_stub_class(class_name, module_path))

        sys.modules[module_path] = stub


def _build_judge_llm():
    """Groq, through Ragas' LangChain wrapper -- reuses the same free-tier
    provider and model already configured for the live agent
    (see agent.py's cloud_llm)."""
    from langchain_openai import ChatOpenAI
    from ragas.llms import LangchainLLMWrapper

    groq_api_key = os.environ.get("GROQ_API_KEY")
    if not groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set in agent/.env.local -- the eval "
            "harness needs it for the LLM judge, same as the live agent."
        )

    chat = ChatOpenAI(
        model="openai/gpt-oss-120b",  # same model already used by agent.py's cloud_llm
        api_key=groq_api_key,
        base_url="https://api.groq.com/openai/v1",
        temperature=0,
    )
    return LangchainLLMWrapper(chat)


def main() -> None:
    rows = asyncio.run(build_ragas_rows())
    print(f"Built {len(rows)} evaluation rows. Running Ragas...\n")

    try:
        _ensure_optional_langchain_integrations_importable()

        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import context_precision, faithfulness

        dataset = Dataset.from_list(rows)
        judge_llm = _build_judge_llm()

        result = evaluate(
            dataset=dataset,
            metrics=[faithfulness, context_precision],
            llm=judge_llm,
        )

        import pandas as pd

        scores_df = result.to_pandas()
        pd.set_option("display.max_colwidth", 60)

        # Ragas has migrated its output column names across versions (e.g.
        # "question" -> "user_input" as part of the metrics.collections
        # migration warned about above). Rather than hardcode one set of
        # names and break again on the next version bump, find whichever
        # question-like column actually exists and build the display list
        # from that plus whichever metric columns evaluate() produced.
        question_col = next(
            (c for c in ("question", "user_input") if c in scores_df.columns),
            None,
        )
        metric_cols = [c for c in ("faithfulness", "context_precision") if c in scores_df.columns]

        if question_col and metric_cols:
            print(scores_df[[question_col] + metric_cols])
        else:
            # Fall back to showing everything rather than crashing again --
            # this tells you exactly what Ragas actually returned this
            # version, so you can adjust the column list above if needed.
            print(
                "Note: expected column names not found (Ragas may have "
                "renamed its output columns again) -- printing all "
                f"available columns instead: {list(scores_df.columns)}\n"
            )
            print(scores_df)

        for metric in metric_cols:
            print(f"\nMean {metric}: {scores_df[metric].mean():.3f}")

        if not metric_cols:
            print(
                "\nCould not find faithfulness/context_precision columns "
                "in the results -- check the printed columns above and "
                "the currently installed Ragas version against "
                "https://docs.ragas.io"
            )

    except Exception:
        print(
            "\nRagas evaluation failed to run -- this is the piece of "
            "Phase 7 most sensitive to the exact installed Ragas version. "
            "Check `python -c \"import ragas; print(ragas.__version__)\"` "
            "against https://docs.ragas.io and adjust the evaluate() call "
            "in this file if the API has moved. Full traceback below:\n"
        )
        raise


if __name__ == "__main__":
    main()