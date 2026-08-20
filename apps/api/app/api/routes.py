from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse

from app.application.service import AgentService
from app.domain.contracts import (
    AgentCreate,
    AgentDefinition,
    AgentEvent,
    DashboardObservability,
    DocumentUploadAccepted,
    DocumentView,
    IngestionJobView,
    KnowledgeBaseCreate,
    KnowledgeBaseView,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    RunObservability,
    RunRequest,
    RunResult,
)
from app.domain.errors import (
    AgentStudioError,
    EntityNotFoundError,
    KnowledgeValidationError,
    ProviderNotConfiguredError,
)
from app.evaluation.contracts import (
    EvaluationCaseCreate,
    EvaluationCaseResultView,
    EvaluationCaseUpdate,
    EvaluationCaseView,
    EvaluationRunView,
    EvaluationSuiteCreate,
    EvaluationSuiteSummary,
    EvaluationSuiteUpdate,
    EvaluationSuiteView,
)
from app.evaluation.service import EvaluationService
from app.knowledge.service import KnowledgeService
from app.memory.contracts import MemoryRecord, MemorySettings, MemorySettingsUpdate
from app.persistence.database import settings

router = APIRouter()


def get_service(request: Request) -> AgentService:
    return cast(AgentService, request.app.state.agent_service)


ServiceDependency = Annotated[AgentService, Depends(get_service)]


def get_knowledge_service(request: Request) -> KnowledgeService:
    return cast(KnowledgeService, request.app.state.knowledge_service)


KnowledgeServiceDependency = Annotated[KnowledgeService, Depends(get_knowledge_service)]


def get_evaluation_service(request: Request) -> EvaluationService:
    return cast(EvaluationService, request.app.state.evaluation_service)


EvaluationServiceDependency = Annotated[EvaluationService, Depends(get_evaluation_service)]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/agents", response_model=AgentDefinition, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, service: ServiceDependency) -> AgentDefinition:
    try:
        return await service.create_agent(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agents", response_model=list[AgentDefinition])
async def list_agents(service: ServiceDependency) -> list[AgentDefinition]:
    return await service.list_agents()


@router.get("/agents/{agent_id}", response_model=AgentDefinition)
async def get_agent(agent_id: UUID, service: ServiceDependency) -> AgentDefinition:
    try:
        return await service.get_agent(agent_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/agents/{agent_id}/memory-settings", response_model=MemorySettings)
async def update_memory_settings(
    agent_id: UUID,
    payload: MemorySettingsUpdate,
    service: ServiceDependency,
) -> MemorySettings:
    try:
        return await service.set_memory_enabled(agent_id, payload.enabled)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agents/{agent_id}/memories", response_model=list[MemoryRecord])
async def list_memories(agent_id: UUID, service: ServiceDependency) -> list[MemoryRecord]:
    try:
        return await service.list_memories(agent_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/agents/{agent_id}/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_memory(
    agent_id: UUID,
    memory_id: UUID,
    service: ServiceDependency,
) -> Response:
    try:
        await service.delete_memory(agent_id, memory_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/agents/{agent_id}/runs", response_model=RunResult, status_code=status.HTTP_202_ACCEPTED
)
async def create_run(
    agent_id: UUID,
    payload: RunRequest,
    service: ServiceDependency,
) -> RunResult:
    try:
        return await service.create_run(agent_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=RunResult)
async def get_run(run_id: UUID, service: ServiceDependency) -> RunResult:
    try:
        return await service.get_run(run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_run(run_id: UUID, service: ServiceDependency) -> RunResult:
    try:
        return await service.cancel_run(run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentStudioError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events", response_model=list[AgentEvent])
async def list_events(run_id: UUID, service: ServiceDependency) -> list[AgentEvent]:
    try:
        return await service.list_events(run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/observability", response_model=RunObservability)
async def get_run_observability(
    run_id: UUID, service: ServiceDependency
) -> RunObservability:
    try:
        return await service.get_run_observability(run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/observability/dashboard", response_model=DashboardObservability)
async def get_dashboard_observability(
    service: ServiceDependency,
) -> DashboardObservability:
    return await service.get_dashboard_observability()


@router.post(
    "/evaluation-suites",
    response_model=EvaluationSuiteView,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_suite(
    payload: EvaluationSuiteCreate,
    service: EvaluationServiceDependency,
) -> EvaluationSuiteView:
    try:
        return await service.create_suite(payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evaluation-suites", response_model=list[EvaluationSuiteSummary])
async def list_evaluation_suites(
    service: EvaluationServiceDependency,
) -> list[EvaluationSuiteSummary]:
    return await service.list_suites()


@router.get("/evaluation-suites/{suite_id}", response_model=EvaluationSuiteView)
async def get_evaluation_suite(
    suite_id: UUID,
    service: EvaluationServiceDependency,
) -> EvaluationSuiteView:
    try:
        return await service.get_suite(suite_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/evaluation-suites/{suite_id}", response_model=EvaluationSuiteView)
async def update_evaluation_suite(
    suite_id: UUID,
    payload: EvaluationSuiteUpdate,
    service: EvaluationServiceDependency,
) -> EvaluationSuiteView:
    try:
        return await service.update_suite(suite_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/evaluation-suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_evaluation_suite(
    suite_id: UUID,
    service: EvaluationServiceDependency,
) -> Response:
    try:
        await service.delete_suite(suite_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/evaluation-suites/{suite_id}/cases",
    response_model=EvaluationCaseView,
    status_code=status.HTTP_201_CREATED,
)
async def create_evaluation_case(
    suite_id: UUID,
    payload: EvaluationCaseCreate,
    service: EvaluationServiceDependency,
) -> EvaluationCaseView:
    try:
        return await service.create_case(suite_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/evaluation-cases/{case_id}", response_model=EvaluationCaseView)
async def update_evaluation_case(
    case_id: UUID,
    payload: EvaluationCaseUpdate,
    service: EvaluationServiceDependency,
) -> EvaluationCaseView:
    try:
        return await service.update_case(case_id, payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/evaluation-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_evaluation_case(
    case_id: UUID,
    service: EvaluationServiceDependency,
) -> Response:
    try:
        await service.delete_case(case_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/evaluation-suites/{suite_id}/runs",
    response_model=EvaluationRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_evaluation_run(
    suite_id: UUID,
    service: EvaluationServiceDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> EvaluationRunView:
    try:
        return await service.start_run(suite_id, idempotency_key)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evaluation-runs/{evaluation_run_id}", response_model=EvaluationRunView)
async def get_evaluation_run(
    evaluation_run_id: UUID,
    service: EvaluationServiceDependency,
) -> EvaluationRunView:
    try:
        return await service.get_run(evaluation_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/evaluation-runs/{evaluation_run_id}/results",
    response_model=list[EvaluationCaseResultView],
)
async def list_evaluation_results(
    evaluation_run_id: UUID,
    service: EvaluationServiceDependency,
) -> list[EvaluationCaseResultView]:
    try:
        return await service.list_results(evaluation_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/evaluation-runs/{evaluation_run_id}/cancel",
    response_model=EvaluationRunView,
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_evaluation_run(
    evaluation_run_id: UUID,
    service: EvaluationServiceDependency,
) -> EvaluationRunView:
    try:
        return await service.cancel_run(evaluation_run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/stream")
async def stream_events(
    run_id: UUID,
    service: ServiceDependency,
    after_sequence: Annotated[int, Query(ge=0, le=2_147_483_647)] = 0,
) -> StreamingResponse:
    try:
        await service.get_run(run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream_events(run_id, after_sequence):
            data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"
            # Keep the typed event for existing consumers and mirror every envelope onto one
            # stable channel so clients can render event types introduced after they shipped.
            yield f"id: {event.sequence}\nevent: agent.event\ndata: {data}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/knowledge-bases", response_model=KnowledgeBaseView, status_code=status.HTTP_201_CREATED
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate, service: KnowledgeServiceDependency
) -> KnowledgeBaseView:
    return await service.create_base(payload)


@router.get("/knowledge-bases", response_model=list[KnowledgeBaseView])
async def list_knowledge_bases(service: KnowledgeServiceDependency) -> list[KnowledgeBaseView]:
    return await service.list_bases()


@router.get("/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeBaseView)
async def get_knowledge_base(
    knowledge_base_id: UUID, service: KnowledgeServiceDependency
) -> KnowledgeBaseView:
    try:
        return await service.get_base(knowledge_base_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/knowledge-bases/{knowledge_base_id}/documents", response_model=list[DocumentView])
async def list_documents(
    knowledge_base_id: UUID, service: KnowledgeServiceDependency
) -> list[DocumentView]:
    try:
        return await service.list_documents(knowledge_base_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/knowledge-bases/{knowledge_base_id}/documents",
    response_model=DocumentUploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    knowledge_base_id: UUID,
    service: KnowledgeServiceDependency,
    file: Annotated[UploadFile, File(description="UTF-8 text, Markdown, or text PDF")],
) -> DocumentUploadAccepted:
    try:
        data = await file.read(settings.knowledge_max_file_bytes + 1)
        return await service.queue_upload(
            knowledge_base_id,
            file.filename or "",
            file.content_type,
            data,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeValidationError as exc:
        message = str(exc)
        if "exceeds" in message:
            code = status.HTTP_413_CONTENT_TOO_LARGE
        elif "Unsupported file type" in message or "MIME type" in message:
            code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=message) from exc
    finally:
        await file.close()


@router.get("/ingestion-jobs/{job_id}", response_model=IngestionJobView)
async def get_ingestion_job(
    job_id: UUID, service: KnowledgeServiceDependency
) -> IngestionJobView:
    try:
        return await service.get_job(job_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/knowledge-bases/{knowledge_base_id}/search", response_model=KnowledgeSearchResponse
)
async def search_knowledge_base(
    knowledge_base_id: UUID,
    payload: KnowledgeSearchRequest,
    service: KnowledgeServiceDependency,
) -> KnowledgeSearchResponse:
    try:
        return await service.search([knowledge_base_id], payload)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
