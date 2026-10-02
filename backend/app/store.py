"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.seed import SEED_ROWS

# 内部台账（如通信车资源池）不作为独立业务模块进运营概览
INTERNAL_TABLES = {"comm_vehicle"}


def _parse_stamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _format_duration(minutes: int) -> str:
    days, remain = divmod(max(minutes, 0), 24 * 60)
    hours, mins = divmod(remain, 60)
    parts = [f"{days}天"] if days else []
    if hours:
        parts.append(f"{hours}小时")
    if mins or not parts:
        parts.append(f"{mins}分")
    return "".join(parts)


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._sync_site_ledger()

    def module_names(self) -> list[str]:
        return sorted(name for name in self._tables if name not in INTERNAL_TABLES)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def _sync_site_ledger(self) -> None:
        """示例数据启动时对账：已收口保障的结论补写进对应站点台账，避免台账缺历史。"""
        sites = {str(row.get("基站编号", "")).strip(): row for row in self.rows("site")}
        for entry in self.rows("emergency"):
            if entry.get("status") != "已撤离":
                continue
            site = sites.get(str(entry.get("所属站点编号") or "").strip())
            if site is None:
                location = str(entry.get("保障地点") or "").strip()
                site = next(
                    (
                        row
                        for row in self.rows("site")
                        if location in (str(row.get("基站编号", "")).strip(), str(row.get("基站名称", "")).strip())
                    ),
                    None,
                )
            if site is None:
                continue
            arrived, left = _parse_stamp(entry.get("到达时间")), _parse_stamp(entry.get("撤离时间"))
            duration = _format_duration(int((left - arrived).total_seconds() // 60)) if arrived and left else None
            records = site.setdefault("应急保障记录", [])
            if any(str(item.get("保障编号")) == str(entry.get("保障编号")) for item in records):
                continue
            records.append(
                {
                    "保障编号": entry.get("保障编号"),
                    "保障地点": entry.get("保障地点"),
                    "撤离时间": entry.get("撤离时间"),
                    "到场时长": duration,
                    "保障结论": entry.get("保障结论"),
                }
            )
            site["最近应急保障"] = f"{entry.get('撤离时间')} {entry.get('保障编号')}：{entry.get('保障结论')}"

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
