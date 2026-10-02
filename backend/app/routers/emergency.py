"""应急通信接口：维护应急保障，覆盖报障登记、调派车辆、到场登记、撤离收口等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.emergency import EmergencyService

router = APIRouter(prefix="/api/emergency", tags=["应急通信"])

service = EmergencyService()

LIST_FIELDS = [
    "保障编号", "保障类型", "保障地点", "所属站点编号", "通信车编号", "保障人员",
    "通知时间", "调派时间", "到达时间", "撤离时间", "到场时长", "保障结论", "保障状态",
]
STATUSES = ["待响应", "保障中", "已撤离"]
ACTIONS = ["调派", "到场登记", "撤离收口", "绑定站点"]
SORTS = ["duration_asc", "duration_desc"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按保障编号、保障地点或通信车编号检索"),
    status: str | None = Query(default=None, description="待响应、保障中、已撤离"),
    sort: str | None = Query(default=None, description="到场时长排序：duration_asc、duration_desc"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号/地点/车辆、状态过滤应急保障列表，可按到场时长排序；没有数据时返回空页。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    if sort and sort not in SORTS:
        raise HTTPException(status_code=400, detail=f"排序口径 {sort} 不支持，请使用 {('、'.join(SORTS))}")
    items, total = service.list_entries(keyword=keyword, status=status, sort=sort, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/vehicles")
def list_vehicles() -> dict[str, Any]:
    """通信车台账：调派前先看每辆车当前是否可用、被哪条保障占用。"""
    items = service.list_vehicles()
    return {"total": len(items), "items": items}


@router.get("/sites")
def list_sites() -> dict[str, Any]:
    """可绑定的站点清单：撤离收口时保障结论要写回站点台账。"""
    items = service.list_site_options()
    return {"total": len(items), "items": items}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出应急通信清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "emergency", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条应急保障明细（含时间线）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"应急保障 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记报障：先落成待响应；同地点短时间内重复报障自动并入同一条时间线。"""
    entry, missing, merged = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if merged:
        return ActionResult(
            ok=True,
            message=(
                f"该地点 120 分钟内已有在途保障 {entry['保障编号']}，重复报障已并入同一条时间线，"
                "不另开新保障"
            ),
            entry=entry,
        )
    return ActionResult(ok=True, message=f"报障已登记为待响应，保障编号 {entry['保障编号']}", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条保障执行调派、到场登记、撤离收口、绑定站点；不满足条件的动作会被拦下并说明原因。"""
    entry, message = service.run_action(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
