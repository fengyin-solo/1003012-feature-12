"""应急通信业务规则：报障登记、同地点并单、调派、到场与撤离收口的时间线都收在这里。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "emergency"
VEHICLE_MODULE = "comm_vehicle"
SITE_MODULE = "site"

REQUIRED_FIELDS = ["保障类型", "保障地点"]
STATUS_ORDER = ["待响应", "保障中", "已撤离"]
ACTIVE_STATUSES = {"待响应", "保障中"}

# 同一保障地点在该时间窗内重复报障，只并成一次保障
MERGE_WINDOW_MINUTES = 120


def parse_time(value: Any) -> datetime | None:
    """把登记的时间解析成 datetime；认不出来时返回 None，由调用方决定是否拦下。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def add_timeline_node(entry: dict[str, Any], node: dict[str, Any]) -> None:
    """时间线按时间戳归位：操作录入顺序不等于实际发生顺序（如先调派、后并入报障）。"""
    timeline = entry.setdefault("timeline", [])
    timeline.append(node)
    timeline.sort(key=lambda item: parse_time(item.get("时间")) or datetime.min)


def format_duration(minutes: int) -> str:
    """到场时长展示：超过一天带天，零头按分钟计。"""
    days, remain = divmod(minutes, 24 * 60)
    hours, mins = divmod(remain, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if mins or not parts:
        parts.append(f"{mins}分")
    return "".join(parts)


class EmergencyService:
    # ------------------------------------------------------------------ 查询
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        sort: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            key = keyword.strip()
            rows = [
                row
                for row in rows
                if key in str(row.get("保障编号", ""))
                or key in str(row.get("保障地点", ""))
                or key in str(row.get("通信车编号", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]

        decorated = [self._decorate(row) for row in rows]
        if sort in {"duration_asc", "duration_desc"}:
            decorated.sort(
                key=lambda row: (row["到场时长分钟"] is None, row["到场时长分钟"] or 0),
                reverse=sort == "duration_desc",
            )

        total = len(decorated)
        start = max(page - 1, 0) * size
        return decorated[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def list_vehicles(self) -> list[dict[str, Any]]:
        """通信车台账：实时带出当前是否可用，被哪条在途保障占着。"""
        occupied = self._occupied_vehicles()
        result: list[dict[str, Any]] = []
        for vehicle in store.rows(VEHICLE_MODULE):
            code = str(vehicle.get("车辆编号", ""))
            holder = occupied.get(code)
            if holder:
                available = False
                reason = f"被保障 {holder} 占用"
            elif str(vehicle.get("车辆状态", "")) != "可用":
                available = False
                reason = f"车辆状态为「{vehicle.get('车辆状态')}」"
            else:
                available = True
                reason = ""
            result.append({**vehicle, "可用": available, "占用原因": reason, "占用保障编号": holder})
        return result

    def list_site_options(self) -> list[dict[str, Any]]:
        """站点下拉：撤离收口时要把结论写回站点台账，先让保障能绑定到具体站点。"""
        return [
            {"id": row.get("id"), "基站编号": row.get("基站编号", ""), "基站名称": row.get("基站名称", "")}
            for row in store.rows(SITE_MODULE)
        ]

    # ------------------------------------------------------------------ 登记
    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记报障；返回 (记录, 缺失字段, 是否并入已有保障)。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False

        notify_at = parse_time(values.get("通知时间")) or datetime.now()
        location = str(values.get("保障地点")).strip()

        merged = self._merge_duplicate(location, notify_at, values)
        if merged is not None:
            return merged, [], True

        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["保障编号"] = self._next_code(rows, notify_at)
        entry["保障类型"] = str(values.get("保障类型")).strip()
        entry["保障地点"] = location
        entry["所属站点编号"] = self._bind_site_code(values.get("所属站点编号"))
        entry["通信车编号"] = None
        entry["保障人员"] = None
        entry["通知时间"] = notify_at.strftime("%Y-%m-%d %H:%M")
        entry["调派时间"] = None
        entry["到达时间"] = None
        entry["撤离时间"] = None
        entry["保障结论"] = None
        entry["合并报障数"] = 0
        entry["补充报障"] = []
        entry["timeline"] = [
            {"时间": entry["通知时间"], "节点": "接到通知", "说明": entry["保障类型"]}
        ]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, [], False

    # ------------------------------------------------------------------ 动作
    def run_action(
        self, entry_id: int, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"应急保障 {entry_id} 不存在或已归档"
        action = str(values.get("action") or "").strip()
        if action == "调派":
            return self._dispatch(entry, values)
        if action == "到场登记":
            return self._arrive(entry, values)
        if action == "撤离收口":
            return self._withdraw(entry, values)
        if action == "绑定站点":
            return self._bind_site(entry, values)
        return None, f"动作「{action}」不属于应急通信可执行范围"

    # ------------------------------------------------------------------ 调派
    def _dispatch(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] != "待响应":
            return None, f"保障 {entry['保障编号']} 当前为「{entry['status']}」，不能重复调派"
        vehicle_code = str(values.get("通信车编号") or "").strip()
        members = str(values.get("保障人员") or "").strip()
        if not vehicle_code:
            return None, "调派必须选择一辆通信车"
        if not members:
            return None, "调派必须指定保障人员"

        vehicle = self._find_vehicle(vehicle_code)
        if vehicle is None:
            return None, f"通信车 {vehicle_code} 不在车辆台账中，无法调派"
        holder = self._occupied_vehicles().get(vehicle_code)
        if holder:
            return None, f"通信车 {vehicle_code} 已被保障 {holder} 占用，不能重复调派"
        if str(vehicle.get("车辆状态", "")) != "可用":
            return None, f"通信车 {vehicle_code} 当前状态为「{vehicle.get('车辆状态')}」，不能调派"

        dispatch_at = parse_time(values.get("调派时间")) or datetime.now()
        notified = parse_time(entry.get("通知时间"))
        if notified and dispatch_at < notified:
            return None, "调派时间不能早于接到通知时间"

        site_code = self._bind_site_code(values.get("所属站点编号"))
        if values.get("所属站点编号") and site_code is None:
            return None, f"站点 {values.get('所属站点编号')} 不在站点台账中，请重新选择"

        entry["通信车编号"] = vehicle_code
        entry["保障人员"] = members
        entry["调派时间"] = dispatch_at.strftime("%Y-%m-%d %H:%M")
        if site_code:
            entry["所属站点编号"] = site_code
        entry["status"] = "保障中"
        entry["pending"] = True
        add_timeline_node(
            entry,
            {
                "时间": entry["调派时间"],
                "节点": "调派",
                "说明": f"调派通信车 {vehicle_code}，保障人员：{members}",
            },
        )
        return entry, f"通信车 {vehicle_code}（当前可用）已调派，保障 {entry['保障编号']} 进入保障中"

    # ------------------------------------------------------------------ 到场
    def _arrive(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] != "保障中":
            return None, f"保障 {entry['保障编号']} 当前为「{entry['status']}」，不能登记到场"
        if not entry.get("通信车编号"):
            return None, "尚未调派通信车，不能登记到场"
        arrive_at = parse_time(values.get("到达时间"))
        if arrive_at is None:
            return None, "到场登记必须填写到达时间"
        dispatched = parse_time(entry.get("调派时间"))
        if dispatched and arrive_at < dispatched:
            return None, "到达时间不能早于调派时间"

        entry["到达时间"] = arrive_at.strftime("%Y-%m-%d %H:%M")
        add_timeline_node(
            entry,
            {"时间": entry["到达时间"], "节点": "到场", "说明": f"通信车 {entry['通信车编号']} 到达保障地点"},
        )
        return entry, f"保障 {entry['保障编号']} 到场时间已分段登记，当前仍处于保障中"

    # ------------------------------------------------------------------ 撤离
    def _withdraw(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] != "保障中":
            return None, f"保障 {entry['保障编号']} 当前为「{entry['status']}」，不能撤离收口"
        if not entry.get("到达时间"):
            return None, "到场时间尚未登记，请先分段登记到场时间"

        leave_at = parse_time(values.get("撤离时间"))
        if leave_at is None:
            return None, "撤离收口必须填写撤离时间，撤离时间没填完不许收口"
        arrived = parse_time(entry["到达时间"])
        if arrived and leave_at < arrived:
            return None, "撤离时间不能早于到达时间"

        conclusion = str(values.get("保障结论") or "").strip()
        if not conclusion:
            return None, "撤离收口必须填写保障结论，结论缺失不许收口"

        site = self._resolve_site(entry)
        if site is None:
            hint = entry.get("所属站点编号") or entry.get("保障地点")
            return None, f"未在站点台账匹配到「{hint}」，保障结论无法写回；请先绑定所属站点再收口"

        entry["撤离时间"] = leave_at.strftime("%Y-%m-%d %H:%M")
        entry["保障结论"] = conclusion
        entry["status"] = "已撤离"
        entry["pending"] = False
        add_timeline_node(
            entry,
            {"时间": entry["撤离时间"], "节点": "撤离收口", "说明": conclusion},
        )
        self._write_back_site(site, entry)
        return (
            entry,
            f"保障 {entry['保障编号']} 已收口，结论已写回站点台账（{site.get('基站编号')} {site.get('基站名称')}），"
            f"通信车 {entry.get('通信车编号')} 已释放",
        )

    # ------------------------------------------------------------------ 绑定站点
    def _bind_site(self, entry: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        if entry["status"] not in ACTIVE_STATUSES:
            return None, f"保障 {entry['保障编号']} 已收口，不能再改站点绑定"
        site_code = self._bind_site_code(values.get("所属站点编号"))
        if site_code is None:
            return None, f"站点 {values.get('所属站点编号')} 不在站点台账中，请重新选择"
        entry["所属站点编号"] = site_code
        site = self._find_site(site_code)
        return entry, f"保障 {entry['保障编号']} 已绑定站点 {site_code} {site.get('基站名称', '') if site else ''}"

    # ------------------------------------------------------------------ 辅助
    def _merge_duplicate(
        self, location: str, notify_at: datetime, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        """同地点、时间窗内、且尚未收口的报障并入最近一条；已撤离的不并。"""
        candidates: list[tuple[datetime, dict[str, Any]]] = []
        for row in store.rows(MODULE):
            if row.get("status") not in ACTIVE_STATUSES:
                continue
            if str(row.get("保障地点", "")).strip() != location:
                continue
            notified = parse_time(row.get("通知时间"))
            if notified is None or abs(notify_at - notified) > timedelta(minutes=MERGE_WINDOW_MINUTES):
                continue
            candidates.append((notified, row))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        target = candidates[-1][1]
        stamp = notify_at.strftime("%Y-%m-%d %H:%M")
        detail = f"{values.get('保障类型')}（重复报障并入本条时间线）"
        target.setdefault("补充报障", []).append(f"{stamp} {detail}")
        target["合并报障数"] = int(target.get("合并报障数") or 0) + 1
        add_timeline_node(target, {"时间": stamp, "节点": "补充报障", "说明": detail})
        return target

    def _next_code(self, rows: list[dict[str, Any]], notify_at: datetime) -> str:
        prefix = f"EMER-{notify_at.strftime('%m%d')}-"
        seq = 1
        for row in rows:
            code = str(row.get("保障编号", ""))
            if code.startswith(prefix):
                try:
                    seq = max(seq, int(code.rsplit("-", 1)[-1]) + 1)
                except ValueError:
                    continue
        return f"{prefix}{seq:02d}"

    def _find_vehicle(self, code: str) -> dict[str, Any] | None:
        for vehicle in store.rows(VEHICLE_MODULE):
            if str(vehicle.get("车辆编号", "")) == code:
                return vehicle
        return None

    def _occupied_vehicles(self) -> dict[str, str]:
        """车辆被未收口的保障占着即视为占用；撤离收口后自动释放。"""
        occupied: dict[str, str] = {}
        for row in store.rows(MODULE):
            if row.get("status") in ACTIVE_STATUSES and row.get("通信车编号"):
                occupied[str(row["通信车编号"])] = str(row.get("保障编号", ""))
        return occupied

    def _find_site(self, code: str | None) -> dict[str, Any] | None:
        if not code:
            return None
        code = str(code).strip()
        for site in store.rows(SITE_MODULE):
            if str(site.get("基站编号", "")).strip() == code:
                return site
        return None

    def _bind_site_code(self, value: Any) -> str | None:
        """输入既可能是编号也可能是「编号 名称」的下拉值，统一解析成编号并校验存在。"""
        if value is None:
            return None
        code = str(value).strip().split()[0]
        return code if self._find_site(code) is not None else None

    def _resolve_site(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        site = self._find_site(entry.get("所属站点编号"))
        if site is not None:
            return site
        location = str(entry.get("保障地点") or "").strip()
        if not location:
            return None
        for row in store.rows(SITE_MODULE):
            if location in (str(row.get("基站编号", "")).strip(), str(row.get("基站名称", "")).strip()):
                return row
        return None

    def _write_back_site(self, site: dict[str, Any], entry: dict[str, Any]) -> None:
        """撤离后把保障结论追加进站点台账，并刷新最近一次应急保障摘要。"""
        records = site.setdefault("应急保障记录", [])
        if not any(str(item.get("保障编号")) == str(entry["保障编号"]) for item in records):
            records.append(
                {
                    "保障编号": entry["保障编号"],
                    "保障地点": entry.get("保障地点"),
                    "撤离时间": entry["撤离时间"],
                    "到场时长": self._duration_text(entry),
                    "保障结论": entry["保障结论"],
                }
            )
        latest = self._latest_record(records)
        if latest is not None:
            site["最近应急保障"] = f"{latest['撤离时间']} {latest['保障编号']}：{latest['保障结论']}"

    def _latest_record(self, records: list[dict[str, Any]]) -> dict[str, Any] | None:
        parsed = [(parse_time(item.get("撤离时间")), item) for item in records]
        parsed = [(stamp, item) for stamp, item in parsed if stamp is not None]
        if not parsed:
            return records[-1] if records else None
        return max(parsed, key=lambda item: item[0])[1]

    def _duration_minutes(self, row: dict[str, Any]) -> int | None:
        arrived = parse_time(row.get("到达时间"))
        if arrived is None:
            return None
        left = parse_time(row.get("撤离时间"))
        if left is None:
            if row.get("status") == "保障中":
                left = datetime.now()
            else:
                return None
        minutes = int((left - arrived).total_seconds() // 60)
        return max(minutes, 0)

    def _duration_text(self, row: dict[str, Any]) -> str | None:
        minutes = self._duration_minutes(row)
        if minutes is None:
            return None
        text = format_duration(minutes)
        if row.get("status") == "保障中" and not row.get("撤离时间"):
            text += "（进行中）"
        return text

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """列表行带出到场时长，支持排序；不改动仓库里的原始记录。"""
        decorated = dict(row)
        minutes = self._duration_minutes(row)
        decorated["到场时长分钟"] = minutes
        decorated["到场时长"] = self._duration_text(row)
        return decorated
