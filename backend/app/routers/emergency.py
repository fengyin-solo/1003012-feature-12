"""应急通信接口：按时间线登记保障，覆盖接报登记、调派、到场、分段、撤离收口与通信车台账。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.emergency import EmergencyService

router = APIRouter(prefix="/api/emergency", tags=["应急通信"])

service = EmergencyService()

STATUSES = ["待响应", "保障中", "已撤离"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按保障编号或保障类型检索"),
    status: str | None = Query(default=None, description="待响应、保障中、已撤离"),
    location: str | None = Query(default=None, description="按保障地点检索"),
    sort_duration: bool = Query(default=False, description="为 true 时按到场时长从长到短排序"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、类型、地点与状态过滤；到场时长排序由后端统一口径计算。"""
    if size > 200:
        return PageResult(items=[], total=0, page=page, size=size)
    items, total = service.list_entries(
        keyword=keyword, status=status, location=location,
        sort_duration=sort_duration, page=page, size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """看板统计：各状态任务数与当前可用通信车数。"""
    return {"items": service.stats()}


@router.get("/vehicles")
def list_vehicles() -> dict[str, Any]:
    """通信车台账：带出当前可用状态，占用中的车标注占用它的保障。"""
    return {"items": service.list_vehicles()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出应急通信清单：按到场时长排序的全量数据。"""
    items, total = service.list_entries(sort_duration=True, page=1, size=10000)
    return {"module": "emergency", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict[str, Any]:
    """读取单条应急保障明细（含完整时间线）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        return {"ok": False, "message": f"应急保障 {entry_id} 不存在或已归档"}
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """接到保障通知后登记待响应；同地点短时间内的重复报障自动并入原时间线。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        if missing == ["通知时间"]:
            return ActionResult(ok=False, message="通知时间格式不正确，应为 YYYY-MM-DD HH:MM")
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    merged = bool(entry and int(entry.get("报障次数", 1)) > 1 and entry.get("timeline")
                  and entry["timeline"][-1].get("action") == "重复报障并入")
    if merged:
        return ActionResult(ok=True, message=f"该地点 24 小时内已有未收口保障，已并入 {entry['保障编号']} 时间线", entry=entry)
    return ActionResult(ok=True, message="应急保障已登记为待响应", entry=entry)


@router.post("/{entry_id}/dispatch", response_model=ActionResult)
def dispatch(entry_id: int, payload: EntryPayload) -> ActionResult:
    """调派通信车与保障人员：占用中的车辆不允许重复调派，成功后进入保障中。"""
    entry, message = service.dispatch(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/arrive", response_model=ActionResult)
def arrive(entry_id: int, payload: EntryPayload) -> ActionResult:
    """登记首次到场时间；到场与撤离分段记录，到场前不能撤离。"""
    entry, message = service.arrive(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/segments", response_model=ActionResult)
def record_segment(entry_id: int, payload: EntryPayload) -> ActionResult:
    """到场后的分段记录（转场、值守交接等），补进同一条时间线。"""
    entry, message = service.record_segment(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/withdraw", response_model=ActionResult)
def withdraw(entry_id: int, payload: EntryPayload) -> ActionResult:
    """撤离收口：撤离时间与保障结论缺一不可，收口后结论写回站点台账并释放通信车。"""
    entry, message = service.withdraw(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
