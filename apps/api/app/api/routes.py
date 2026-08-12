from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.application.service import AgentService
from app.domain.contracts import AgentCreate, AgentDefinition, AgentEvent, RunRequest, RunResult
from app.domain.errors import AgentStudioError, EntityNotFoundError, ProviderNotConfiguredError

router = APIRouter()


def get_service(request: Request) -> AgentService:
    return cast(AgentService, request.app.state.agent_service)


ServiceDependency = Annotated[AgentService, Depends(get_service)]


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


@router.get("/runs/{run_id}/stream")
async def stream_events(
    run_id: UUID,
    service: ServiceDependency,
    after_sequence: int = 0,
) -> StreamingResponse:
    try:
        await service.get_run(run_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def event_source() -> AsyncIterator[str]:
        async for event in service.stream_events(run_id, after_sequence):
            data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
            yield f"id: {event.sequence}\nevent: {event.type}\ndata: {data}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
