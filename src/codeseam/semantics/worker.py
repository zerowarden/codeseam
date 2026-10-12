"""The packaged TypeScript worker and the policy for starting it."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from codeseam.semantics.provider import SemanticProvider
from codeseam.semantics.transport import StdioSemanticProvider

TYPESCRIPT_WORKER = "semantic_worker/typescript/src/main.mjs"
UNTRUSTED_REASON = "semantic_provider_untrusted"
NODE_MISSING_REASON = "semantic_worker_node_not_found"


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    provider: SemanticProvider | None
    unavailable_reason: str = ""


def typescript_worker_script() -> Path:
    return Path(str(resources.files("codeseam.resources").joinpath(TYPESCRIPT_WORKER)))


def typescript_provider(repo_root: Path, *, trusted: bool) -> ProviderChoice:
    """The TypeScript worker, started only for repositories whose code is trusted.

    The worker loads the `typescript` package from the analysed repository, so
    starting it runs that repository's installed code. It needs Node on `PATH`.
    """

    if not trusted:
        return ProviderChoice(None, UNTRUSTED_REASON)
    node = shutil.which("node")
    if node is None:
        return ProviderChoice(None, NODE_MISSING_REASON)
    command = (node, str(typescript_worker_script()))
    return ProviderChoice(StdioSemanticProvider(command, cwd=repo_root))


__all__ = [
    "NODE_MISSING_REASON",
    "UNTRUSTED_REASON",
    "ProviderChoice",
    "typescript_provider",
    "typescript_worker_script",
]
