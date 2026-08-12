from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.contracts import KnowledgeSearchRequest, KnowledgeSearchResponse
from app.domain.errors import EntityNotFoundError, KnowledgeValidationError, ToolExecutionError
from app.knowledge.service import KnowledgeService
from app.tools.registry import Tool, ToolDefinition

_knowledge_base_scope: ContextVar[tuple[UUID, ...]] = ContextVar(
    "knowledge_base_scope", default=()
)


class KnowledgeSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4_000)
    top_k: int = Field(default=5, ge=1, le=20)


@contextmanager
def bind_knowledge_bases(knowledge_base_ids: list[UUID]) -> Iterator[None]:
    """Bind immutable agent-owned knowledge access to this asynchronous run context."""

    token = _knowledge_base_scope.set(tuple(knowledge_base_ids))
    try:
        yield
    finally:
        _knowledge_base_scope.reset(token)


class KnowledgeSearchTool:
    """Tool adapter with server-owned collection scope and structured citations."""

    def __init__(self, service: KnowledgeService) -> None:
        self._service = service

    def as_tool(self) -> Tool:
        return Tool(
            definition=ToolDefinition(
                name="knowledge_search",
                description="Search the knowledge bases attached to this agent for cited evidence.",
                input_schema=KnowledgeSearchInput,
                output_schema=KnowledgeSearchResponse,
                timeout_seconds=15.0,
                permissions=frozenset({"knowledge:read"}),
                output_limit=100_000,
            ),
            handler=self.execute,
        )

    async def execute(self, payload: BaseModel) -> KnowledgeSearchResponse:
        search_input = KnowledgeSearchInput.model_validate(payload)
        knowledge_base_ids = list(_knowledge_base_scope.get())
        if not knowledge_base_ids:
            raise ToolExecutionError(
                "Tool 'knowledge_search' has no knowledge bases in its execution scope."
            )
        try:
            return await self._service.search(
                knowledge_base_ids,
                KnowledgeSearchRequest(
                    query=search_input.query,
                    top_k=search_input.top_k,
                    hybrid=True,
                ),
            )
        except (EntityNotFoundError, KnowledgeValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
