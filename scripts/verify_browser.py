"""Real browser paths against verify_native.py's disposable fixture environment."""
import json
import os
import re
import sys
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from auth.service import ph


def main():
    if os.environ.get("KGLEARN_NATIVE_ACCEPTANCE") != "1":
        raise RuntimeError("Browser acceptance is restricted to the isolated native test environment")
    base = os.environ["KGLEARN_TEST_HTTP_URL"]
    temporary, password = "browser-initial-123456", "browser-changed-123456"
    engine = create_engine(os.environ["KGLEARN_TEST_MIGRATION_URL"])
    with engine.begin() as conn:
        for name, role in (("browser_student", "student"), ("browser_teacher", "teacher")):
            conn.execute(text("INSERT INTO users(user_id,username,password_hash,role,must_change_password) VALUES(CAST(:id AS uuid),:username,:password,:role,true)"), {"id": str(uuid.uuid4()), "username": name, "password": ph.hash(temporary), "role": role})
    engine.dispose()
    evidence = {"student_steps": [], "teacher_steps": [], "checks": []}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def login(name, current):
            page.get_by_label("用户名", exact=True).fill(name)
            page.get_by_label("密码", exact=True).fill(current)
            page.get_by_role("button", name="登录", exact=True).click()

        def first_login(name):
            page.goto(base + "/login/")
            login(name, temporary)
            page.wait_for_url("**/change-password/")
            page.get_by_label("当前密码", exact=True).fill(temporary)
            page.get_by_label("新密码", exact=True).fill(password)
            page.get_by_label("确认新密码", exact=True).fill(password)
            page.get_by_role("button", name="保存新密码", exact=True).click()
            page.wait_for_url("**/login/")
            login(name, password)
            page.wait_for_url("**/graph/")
            expect(page.get_by_role("heading", name="跨课程知识图谱")).to_be_visible()

        first_login("browser_student")
        evidence["student_steps"] += ["登录页输入账号", "首次改密跳转", "改密撤销会话后重新登录图谱"]
        page.get_by_role("combobox").first.select_option("CO")
        with page.expect_response(lambda response: "/api/v1/graph/subgraph?course_code=CO&hops=1" in response.url):
            page.get_by_role("button", name="查询图谱").click()
        page.wait_for_url("**/graph/?course_code=CO&hops=1")
        page.wait_for_function("document.querySelector('.graph-canvas')?._cyreg?.cy?.nodes().length === 2")
        position = page.locator(".graph-canvas").evaluate("e => { const p=e._cyreg.cy.getElementById('CO03').renderedPosition(); return {x:p.x,y:p.y}; }")
        page.locator(".graph-canvas").click(position=position)
        page.wait_for_url("**/node/?id=CO03")
        expect(page.get_by_role("heading", name="TLB", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="学习状态", exact=True)).to_be_visible()
        evidence["student_steps"] += ["选择CO课程查询", "点击图谱CO03节点", "查看节点/学习状态/关系"]
        page.reload()
        expect(page.get_by_role("heading", name="TLB", exact=True)).to_be_visible()
        page.get_by_role("link", name="开始练习", exact=True).click()
        page.wait_for_url("**/exercise/?node_id=CO03")
        expect(page.get_by_text("Q001 · 难度", exact=False)).to_be_visible()
        page.get_by_role("radio").first.check()
        submissions = []

        def lose_first_response(route):
            if route.request.method != "POST":
                route.continue_()
                return
            submissions.append(route.request.post_data_json)
            if len(submissions) == 1:
                response = route.fetch()
                assert response.status == 201
                route.abort("failed")
            else:
                route.continue_()

        page.route("**/api/v1/exercises/attempts", lose_first_response)
        page.get_by_role("button", name="提交答案", exact=True).click()
        expect(page.get_by_role("alert")).to_be_visible()
        page.get_by_role("button", name="提交答案", exact=True).click()
        expect(page.locator(".result-box strong")).to_have_text("本次回答正确")
        assert len(submissions) == 2 and submissions[0]["client_submission_id"] == submissions[1]["client_submission_id"]
        expect(page.locator(".history-item")).to_have_count(1)
        page.unroute("**/api/v1/exercises/attempts", lose_first_response)
        evidence["student_steps"] += ["开始练习", "提交Q001答案A并重试", "查看正确反馈"]
        evidence["checks"].append("丢失已提交响应后重试复用UUID，历史仅1条")
        page.get_by_role("link", name="学习记录", exact=True).click()
        expect(page.get_by_role("heading", name="事件历史", exact=True)).to_be_visible()
        expect(page.locator(".status-row").filter(has_text="CO03")).to_be_visible()
        evidence["student_steps"].append("查看事件及节点状态")
        page.goto(base + "/teacher/acceptance/")
        expect(page.get_by_role("heading", name="暂时无法查看验收摘要")).to_be_visible()
        evidence["checks"].append("学生访问教师摘要显示无权提示")
        page.goto(base + "/graph/")
        for question, label in (("什么是TLB", "已回答"), ("页表是什么", "证据不足"), ("量子纠缠是什么", "暂未覆盖")):
            page.get_by_label("你的问题").fill(question)
            page.get_by_role("button", name="提问", exact=True).click()
            expect(page.get_by_role("heading", name=label, exact=True)).to_be_visible()
        evidence["checks"].append("问答三种业务状态均可显示")
        page.get_by_role("button", name="退出", exact=True).click()
        page.wait_for_url("**/login/")
        page.goto(base + "/learning/")
        page.wait_for_url("**/login/")
        evidence["student_steps"].append("退出后受保护页面回到登录")
        first_login("browser_teacher")
        evidence["teacher_steps"].append("教师登录并完成首次改密")
        page.get_by_role("link", name="教师验收", exact=True).click()
        page.wait_for_url("**/teacher/acceptance/")
        expect(page.get_by_role("heading", name="内容数量", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="证据分布", exact=True)).to_be_visible()
        evidence["teacher_steps"] += ["访问教师验收页", "查看内容数量", "查看证据分布"]
        page.reload()
        expect(page.get_by_role("heading", name="证据分布", exact=True)).to_be_visible()
        page.get_by_role("button", name="退出", exact=True).click()
        page.wait_for_url("**/login/")
        evidence["teacher_steps"].append("教师退出")
        assert not errors, errors
        evidence["checks"].append("无未处理浏览器脚本异常；刷新保留查询参数和会话")
        evidence["browser_version"] = browser.version
        evidence["mode"] = "headless Microsoft Edge, real exported pages + Nginx + PostgreSQL"
        context.close()
        browser.close()
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
