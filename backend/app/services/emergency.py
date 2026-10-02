"""应急通信业务规则：时间线登记、并单、车辆占用校验、撤离收口与站点台账回写。

状态流转只有三段：
  待响应 ──调派车辆/人员──▶ 保障中 ──到场登记(可多次分段)──▶ 保障中 ──撤离登记+结论──▶ 已撤离

同一保障地点、24 小时窗口内、尚未收口（待响应/保障中）的任务，新报障并入原时间线，
不另开记录；通信车在任一未收口任务中被占用即视为不可用，禁止重复调派。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "emergency"
VEHICLE_MODULE = "emergency_vehicle"
SITE_MODULE = "site"

STATUS_PENDING = "待响应"
STATUS_ONGOING = "保障中"
STATUS_CLOSED = "已撤离"
OPEN_STATUSES = (STATUS_PENDING, STATUS_ONGOING)

# 同一地点重复报障的并单窗口
MERGE_WINDOW = timedelta(hours=24)

REQUIRED_FIELDS = ["保障类型", "保障地点"]


def _now_text() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_time(value: Any) -> datetime | None:
    """兼容 datetime-local（2026-09-28T08:00）与纯日期两种写法。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _timeline_add(entry: dict[str, Any], action: str, detail: str, time_text: str, operator: str) -> None:
    entry.setdefault("timeline", []).append(
        {"time": time_text, "action": action, "detail": detail, "operator": operator}
    )


class EmergencyService:
    # ---------------- 列表与明细 ----------------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        location: str | None = None,
        sort_duration: bool = False,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("保障编号", "")) or keyword in str(row.get("保障类型", ""))
            ]
        if location:
            rows = [row for row in rows if location in str(row.get("保障地点", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if sort_duration:
            rows = sorted(rows, key=self._duration_key, reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._decorate(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._decorate(entry) if entry else None

    def _decorate(self, entry: dict[str, Any]) -> dict[str, Any]:
        """补上列表/明细需要的派生字段，不改动存储。"""
        duration_minutes = self._duration_minutes(entry)
        result = dict(entry)
        result["到场时长(分钟)"] = duration_minutes
        result["到场时长"] = self.format_duration(duration_minutes) if duration_minutes is not None else ""
        # 并单会把新节点追加到尾部，展示时统一按时间排回时间线
        result["timeline"] = sorted(
            entry.get("timeline", []),
            key=lambda node: parse_time(node.get("time")) or datetime.min,
        )
        return result

    @staticmethod
    def _duration_minutes(entry: dict[str, Any]) -> int | None:
        arrival = parse_time(entry.get("到场时间"))
        if arrival is None:
            return None
        end = parse_time(entry.get("撤离时间")) or datetime.now()
        minutes = int((end - arrival).total_seconds() // 60)
        return max(minutes, 0)

    @staticmethod
    def _duration_key(entry: dict[str, Any]) -> tuple[int, int]:
        # 没有到场的排最后；已撤离（有完整时长）与进行中按时长比
        minutes = EmergencyService._duration_minutes(entry)
        return (1 if minutes is not None else 0, minutes or 0)

    @staticmethod
    def format_duration(minutes: int | None) -> str:
        if minutes is None:
            return ""
        hours, remain = divmod(minutes, 60)
        if hours and remain:
            return f"{hours}小时{remain}分"
        if hours:
            return f"{hours}小时"
        return f"{remain}分"

    # ---------------- 登记（含并单） ----------------

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing

        location = str(values.get("保障地点")).strip()
        notify_time = str(values.get("通知时间") or "").strip() or _now_text()
        parsed_notify = parse_time(notify_time)
        if parsed_notify is None:
            return None, ["通知时间"]
        operator = str(values.get("登记人") or "").strip()
        detail = str(values.get("报障内容") or "").strip()

        # 并单：同地点、窗口内、还没收口的保障，后到的补进同一条时间线
        merged = self._find_mergeable(location, parsed_notify)
        if merged is not None:
            merged["报障次数"] = int(merged.get("报障次数", 1)) + 1
            merge_detail = f"同地点第 {merged['报障次数']} 次报障"
            if detail:
                merge_detail += f"：{detail}"
            _timeline_add(merged, "重复报障并入", merge_detail, notify_time, operator)
            return self._decorate(merged), []

        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["保障编号"] = self._next_code(rows, parsed_notify)
        entry["保障类型"] = str(values.get("保障类型")).strip()
        entry["保障地点"] = location
        entry["通知时间"] = notify_time
        entry["调派时间"] = None
        entry["通信车编号"] = ""
        entry["保障人员"] = ""
        entry["到场时间"] = None
        entry["到场记录"] = []
        entry["撤离时间"] = None
        entry["保障结论"] = ""
        entry["报障次数"] = 1
        entry["status"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        entry["timeline"] = []
        _timeline_add(
            entry, "接到保障通知",
            detail or f"{entry['保障类型']}，登记待响应",
            notify_time, operator,
        )
        rows.append(entry)
        return self._decorate(entry), []

    def _find_mergeable(self, location: str, notify_time: datetime) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if row.get("status") not in OPEN_STATUSES:
                continue
            if str(row.get("保障地点", "")).strip() != location:
                continue
            anchor = parse_time(row.get("通知时间"))
            if anchor is not None and timedelta(0) <= (notify_time - anchor) <= MERGE_WINDOW:
                return row
        return None

    @staticmethod
    def _next_code(rows: list[dict[str, Any]], notify_time: datetime) -> str:
        prefix = f"EMER-{notify_time.strftime('%Y%m%d')}-"
        seq = max(
            (int(str(row.get("保障编号", ""))[len(prefix):])
             for row in rows if str(row.get("保障编号", "")).startswith(prefix)
             and str(row.get("保障编号", ""))[len(prefix):].isdigit()),
            default=0,
        ) + 1
        return f"{prefix}{seq:03d}"

    # ---------------- 通信车 ----------------

    def list_vehicles(self) -> list[dict[str, Any]]:
        """带出每辆车当前是否可用、被哪条保障占着。"""
        occupied = self._occupied_vehicles()
        result = []
        for vehicle in store.rows(VEHICLE_MODULE):
            row = dict(vehicle)
            occupant = occupied.get(row.get("通信车编号"))
            row["可用状态"] = "占用中" if occupant else "可用"
            row["占用保障编号"] = occupant.get("保障编号", "") if occupant else ""
            row["占用保障地点"] = occupant.get("保障地点", "") if occupant else ""
            result.append(row)
        return result

    def _occupied_vehicles(self) -> dict[str, dict[str, Any]]:
        """未收口任务里已经调派走的车都算占用；一辆车只可能被占一次。"""
        occupied: dict[str, dict[str, Any]] = {}
        for row in store.rows(MODULE):
            if row.get("status") not in OPEN_STATUSES:
                continue
            code = str(row.get("通信车编号") or "").strip()
            if code and code not in occupied:
                occupied[code] = row
        return occupied

    # ---------------- 调派 ----------------

    def dispatch(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应急保障 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_PENDING:
            return None, f"当前状态为「{entry['status']}」，不能重复调派"

        vehicle_code = str(values.get("通信车编号") or "").strip()
        staff = str(values.get("保障人员") or "").strip()
        if not vehicle_code:
            return None, "调派必须选择通信车"
        if not staff:
            return None, "调派必须指派保障人员"

        vehicle = self._find_vehicle(vehicle_code)
        if vehicle is None:
            return None, f"通信车 {vehicle_code} 不在车辆台账中"

        occupant = self._occupied_vehicles().get(vehicle_code)
        if occupant is not None:
            return None, (
                f"通信车 {vehicle_code} 正被保障 {occupant.get('保障编号')}"
                f"（{occupant.get('保障地点')}）占用，不能重复调派"
            )

        dispatch_time = str(values.get("调派时间") or "").strip() or _now_text()
        if parse_time(dispatch_time) is None:
            return None, "调派时间格式不正确，应为 YYYY-MM-DD HH:MM"
        notify_at = parse_time(entry.get("通知时间"))
        dispatch_at = parse_time(dispatch_time)
        if notify_at and dispatch_at and dispatch_at < notify_at:
            return None, "调派时间不能早于接到保障通知的时间"

        operator = str(values.get("调派人") or "").strip()
        entry["通信车编号"] = vehicle_code
        entry["保障人员"] = staff
        entry["调派时间"] = dispatch_time
        entry["status"] = STATUS_ONGOING
        entry["pending"] = True
        _timeline_add(
            entry, "调派通信车",
            f"通信车 {vehicle_code}；人员：{staff}", dispatch_time, operator,
        )
        return self._decorate(entry), f"通信车 {vehicle_code} 已调派，保障进入「保障中」"

    def _find_vehicle(self, code: str) -> dict[str, Any] | None:
        for vehicle in store.rows(VEHICLE_MODULE):
            if str(vehicle.get("通信车编号", "")).strip() == code:
                return vehicle
        return None

    # ---------------- 到场（可分段多次登记） ----------------

    def arrive(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应急保障 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_ONGOING:
            return None, f"当前状态为「{entry['status']}」，只有保障中的任务能登记到场"

        arrive_time = str(values.get("到场时间") or "").strip() or _now_text()
        arrive_at = parse_time(arrive_time)
        if arrive_at is None:
            return None, "到场时间格式不正确，应为 YYYY-MM-DD HH:MM"
        dispatch_at = parse_time(entry.get("调派时间"))
        if dispatch_at and arrive_at < dispatch_at:
            return None, "到场时间不能早于调派时间"
        if entry.get("到场时间"):
            return None, "首次到场时间已登记，不能重复登记"

        operator = str(values.get("登记人") or "").strip()
        note = str(values.get("到场说明") or "").strip()
        entry["到场时间"] = arrive_time
        entry.setdefault("到场记录", []).append({"time": arrive_time, "note": note, "operator": operator})
        _timeline_add(entry, "到场登记", note or "车辆与人员已到场，展开作业", arrive_time, operator)
        return self._decorate(entry), "到场时间已登记"

    def record_segment(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """到场后的分段记录（如转场、夜间值守交接），不改变首次到场时间。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应急保障 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_ONGOING:
            return None, f"当前状态为「{entry['status']}」，不能补记分段"

        seg_time = str(values.get("时间") or values.get("到场时间") or "").strip() or _now_text()
        if parse_time(seg_time) is None:
            return None, "时间格式不正确，应为 YYYY-MM-DD HH:MM"
        note = str(values.get("说明") or values.get("到场说明") or "").strip()
        if not note:
            return None, "分段记录必须填写说明"
        operator = str(values.get("登记人") or "").strip()
        entry.setdefault("到场记录", []).append({"time": seg_time, "note": note, "operator": operator})
        _timeline_add(entry, "保障分段", note, seg_time, operator)
        return self._decorate(entry), "分段记录已补入时间线"

    # ---------------- 撤离收口（强校验 + 台账回写） ----------------

    def withdraw(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应急保障 {entry_id} 不存在或已归档"
        if entry["status"] != STATUS_ONGOING:
            return None, f"当前状态为「{entry['status']}」，不能撤离收口"

        leave_time = str(values.get("撤离时间") or "").strip()
        if not leave_time:
            return None, "撤离时间没填完，不允许收口"
        leave_at = parse_time(leave_time)
        if leave_at is None:
            return None, "撤离时间格式不正确，应为 YYYY-MM-DD HH:MM"
        arrival_at = parse_time(entry.get("到场时间"))
        if arrival_at is None:
            return None, "还没有登记到场时间，不能撤离收口"
        if leave_at < arrival_at:
            return None, "撤离时间不能早于到场时间"

        conclusion = str(values.get("保障结论") or "").strip()
        if not conclusion:
            return None, "保障结论没填完，不允许收口"

        operator = str(values.get("登记人") or "").strip()
        entry["撤离时间"] = leave_time
        entry["保障结论"] = conclusion
        entry["status"] = STATUS_CLOSED
        entry["pending"] = False
        duration = self.format_duration(self._duration_minutes(entry))
        _timeline_add(
            entry, "撤离收口",
            f"{conclusion}（到场时长 {duration}）", leave_time, operator,
        )

        # 结论写回站点台账，便于站点页直接看到最近一次应急保障
        site = self._find_site(str(entry.get("保障地点", "")).strip())
        if site is not None:
            site["最近应急保障"] = (
                f"{entry['保障编号']}｜{leave_time}｜{conclusion}（到场时长 {duration}）"
            )

        message = f"保障已撤离收口，通信车 {entry.get('通信车编号')} 恢复可用；到场时长 {duration}"
        if site is None:
            message += "；保障地点未匹配到站点台账，结论保留在保障记录中"
        return self._decorate(entry), message

    def _find_site(self, location: str) -> dict[str, Any] | None:
        rows = store.rows(SITE_MODULE)
        for row in rows:
            if str(row.get("基站名称", "")).strip() == location:
                return row
        for row in rows:
            if location and (
                location in str(row.get("基站名称", ""))
                or str(row.get("基站名称", "")) in location
            ):
                return row
        return None

    # ---------------- 统计 ----------------

    def stats(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        return [
            {"label": "待响应", "value": sum(1 for r in rows if r.get("status") == STATUS_PENDING)},
            {"label": "保障中", "value": sum(1 for r in rows if r.get("status") == STATUS_ONGOING)},
            {"label": "已撤离", "value": sum(1 for r in rows if r.get("status") == STATUS_CLOSED)},
            {"label": "可用通信车",
             "value": sum(1 for v in self.list_vehicles() if v["可用状态"] == "可用")},
        ]
