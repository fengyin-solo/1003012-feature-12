"""应急通信业务规则冒烟脚本：跑完正常收口与全部拦截口径。"""
from app.services.emergency import EmergencyService
from app.store import store

s = EmergencyService()

# 1. 登记
e, missing = s.create_entry({"保障类型": "故障抢修", "保障地点": "测试站点A",
                             "通知时间": "2026-10-01T10:00", "登记人": "王某"})
assert not missing, missing
print("登记:", e["保障编号"], e["status"])
eid = e["id"]

# 2. 重复报障并单
e2, _ = s.create_entry({"保障类型": "故障抢修", "保障地点": "测试站点A",
                        "通知时间": "2026-10-01T11:00", "报障内容": "又断了"})
assert e2["id"] == eid and e2["报障次数"] == 2
print("并单成功, 报障次数 =", e2["报障次数"])

# 3. 调派 CV-01
e, msg = s.dispatch(eid, {"通信车编号": "CV-03", "保障人员": "张三",
                          "调派时间": "2026-10-01T10:20"})
assert e is not None, msg
print("调派:", msg)

# 4. 同车再调派 -> 拒绝
e3, _ = s.create_entry({"保障类型": "防汛", "保障地点": "测试站点B",
                        "通知时间": "2026-10-01T10:00"})
e3id = e3["id"]
e3, msg = s.dispatch(e3id, {"通信车编号": "CV-03", "保障人员": "李四",
                            "调派时间": "2026-10-01T10:30"})
assert e3 is None and "占用" in msg
print("重复调派被拦:", msg)

# 4b. 车辆列表带出占用
veh = {v["通信车编号"]: v for v in s.list_vehicles()}
assert veh["CV-03"]["可用状态"] == "占用中" and veh["CV-03"]["占用保障编号"]
assert veh["CV-02"]["可用状态"] == "可用"
print("车辆状态:", veh["CV-03"]["可用状态"], "/", veh["CV-02"]["可用状态"])

# 5. 不存在的车
e3, msg = s.dispatch(e3id, {"通信车编号": "CV-99", "保障人员": "李四"})
assert e3 is None
print("黑车被拦:", msg)

# 6. 缺人员
e3, msg = s.dispatch(e3id, {"通信车编号": "CV-02", "保障人员": ""})
assert e3 is None
print("缺人员被拦:", msg)

# 7. 未到场就撤离 -> 拒绝
e, msg = s.withdraw(eid, {"撤离时间": "2026-10-01T12:00", "保障结论": "完成"})
assert e is None
print("未到场撤离被拦:", msg)

# 8. 到场
e, msg = s.arrive(eid, {"到场时间": "2026-10-01T11:05", "登记人": "张三"})
assert e is not None
print("到场:", msg)

# 9. 到场早于调派 -> 拒绝
bad, msg = s.create_entry({"保障类型": "x", "保障地点": "C", "通知时间": "2026-10-01T10:00"})
bad, msg = s.dispatch(bad["id"], {"通信车编号": "CV-04", "保障人员": "p",
                                  "调派时间": "2026-10-01T11:00"})
bad, msg = s.arrive(bad["id"], {"到场时间": "2026-10-01T10:30"})
assert bad is None
print("到场早于调派被拦:", msg)

# 10. 撤离缺时间/缺结论
e, msg = s.withdraw(eid, {"保障结论": "完成"})
assert e is None and "撤离时间" in msg
print("缺撤离时间被拦:", msg)
e, msg = s.withdraw(eid, {"撤离时间": "2026-10-01T12:00", "保障结论": "  "})
assert e is None and "结论" in msg
print("缺结论被拦:", msg)

# 11. 分段记录
e, msg = s.record_segment(eid, {"时间": "2026-10-01T11:30",
                                "说明": "完成发电切换", "登记人": "张三"})
assert e is not None
print("分段:", msg)

# 12. 正常收口
e, msg = s.withdraw(eid, {"撤离时间": "2026-10-01T13:05",
                          "保障结论": "信号恢复正常", "登记人": "张三"})
assert e["status"] == "已撤离" and e["pending"] is False
print("收口:", msg)
assert e["到场时长"] == "2小时", e["到场时长"]

# 13. 站点台账回写（保障地点不在站点表里 -> 提示但不失败）
assert "未匹配到站点台账" in msg

# 14. 车辆释放
e3, msg = s.dispatch(e3id, {"通信车编号": "CV-03", "保障人员": "李四",
                            "调派时间": "2026-10-01T13:30"})
assert e3 is not None
print("释放后可再派:", msg)

# 15. 超窗口不并单
e4, _ = s.create_entry({"保障类型": "故障", "保障地点": "测试站点A",
                        "通知时间": "2026-10-03T10:00"})
assert e4["id"] != eid
print("超24h新开:", e4["保障编号"])

# 16. 排序：首条即到场时长最大值；未到场的排最后
items, _ = s.list_entries(sort_duration=True, page=1, size=100)
durations = [i["到场时长(分钟)"] for i in items]
present = [d for d in durations if d is not None]
assert present == sorted(present, reverse=True)
assert all(d is None for d in durations[len(present):])
print("排序首条:", items[0]["保障编号"], items[0]["到场时长"])

# 17. 时间线
row = store.rows("emergency")[[r["id"] for r in store.rows("emergency")].index(eid)]
print("时间线:")
for t in row["timeline"]:
    print("  ", t["time"], t["action"], "-", t["detail"])

# 18. 已撤离不能重复收口
e, msg = s.withdraw(eid, {"撤离时间": "2026-10-01T14:00", "保障结论": "再次"})
assert e is None
print("重复收口被拦:", msg)

# 19. 站点台账回写命中：用站点表里的名称
site_name = store.rows("site")[0]["基站名称"]
e5, _ = s.create_entry({"保障类型": "保障", "保障地点": site_name,
                        "通知时间": "2026-10-01T08:00"})
s.dispatch(e5["id"], {"通信车编号": "CV-02", "保障人员": "钱七",
                      "调派时间": "2026-10-01T08:10"})
s.arrive(e5["id"], {"到场时间": "2026-10-01T09:00"})
e5, msg = s.withdraw(e5["id"], {"撤离时间": "2026-10-01T10:00",
                                "保障结论": "保障到位"})
assert e5 is not None and "未匹配" not in msg
assert store.rows("site")[0].get("最近应急保障", "").startswith(e5["保障编号"])
print("台账回写命中:", store.rows("site")[0]["最近应急保障"])

print("\n全部通过")
