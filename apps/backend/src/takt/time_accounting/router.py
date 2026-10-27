from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from takt.time_accounting.calculation import (
    Attendance,
    Break,
    InvalidIntervals,
    calculate,
    calculate_schedule,
)
from takt.time_accounting.schemas import (
    CalculationInput,
    CalculationOutput,
    ScheduledCalculationInput,
    ScheduledCalculationOutput,
)

router = APIRouter(prefix="/api/v1/time", tags=["Time accounting"])


@router.post("/calculate", response_model=CalculationOutput, operation_id="calculateWorkday")
def calculate_workday(body: CalculationInput, request: Request) -> CalculationOutput:
    try:
        summary = calculate(
            work_date=body.work_date,
            required_minutes=body.required_minutes,
            intervals=tuple(
                Attendance(
                    started_at=item.started_at,
                    ended_at=item.ended_at,
                    breaks=tuple(
                        Break(started_at=pause.started_at, ended_at=pause.ended_at)
                        for pause in item.breaks
                    ),
                )
                for item in body.intervals
            ),
            as_of=body.as_of or datetime.now(UTC),
            time_zone=ZoneInfo(request.app.state.settings.time_zone),
        )
    except InvalidIntervals as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_intervals", "message": str(exc)}
        ) from exc
    return CalculationOutput.model_validate(summary)


@router.post(
    "/day", response_model=ScheduledCalculationOutput, operation_id="calculateScheduledDay"
)
def calculate_scheduled_day(
    body: ScheduledCalculationInput, request: Request
) -> ScheduledCalculationOutput:
    try:
        result = calculate_schedule(
            work_date=body.work_date,
            end_time=body.end_time,
            intervals=tuple(
                Attendance(
                    item.started_at,
                    item.ended_at,
                    tuple(Break(pause.started_at, pause.ended_at) for pause in item.breaks),
                )
                for item in body.intervals
            ),
            as_of=body.as_of or datetime.now(UTC),
            time_zone=ZoneInfo(request.app.state.settings.time_zone),
        )
    except InvalidIntervals as exc:
        raise HTTPException(
            status_code=422, detail={"code": "invalid_intervals", "message": str(exc)}
        ) from exc
    return ScheduledCalculationOutput.model_validate(result)
