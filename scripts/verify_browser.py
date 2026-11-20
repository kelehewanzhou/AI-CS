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
        # Exercise the real default page with the planned 91-node content size.
        conn.execute(text("INSERT INTO knowledge_nodes(node_id,course_code,title,chapter_scope,description,aliases,scope_tags) SELECT 'DS' || (1000+i)::text,'DS','Browser node ' || i::text,'test','test',ARRAY[]::text[],ARRAY[]::text[] FROM generate_series(1,86) AS i"))
    evidence = {"student_steps": [], "teacher_steps": [], "checks": []}
    with sync_playwright() as playwright:
        channel = os.environ.get("KGLEARN_BROWSER_CHANNEL", "msedge")
        browser = playwright.chromium.launch(headless=True, **({"channel": channel} if channel != "chromium" else {}))
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        errors = []
        external_requests = set()
        context.on("request", lambda request: external_requests.add(request.url.split("?", 1)[0])
                   if request.url.startswith(("http://", "https://"))
                   and not request.url.startswith(base.rstrip("/") + "/") else None)
        overview_requests = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: overview_requests.append(request.url)
                if re.search(r"/api/v1/graph/subgraph(?:\?|$)", request.url)
                and not re.search(r"[?&](?:node_id|course_code|q)=", request.url) else None)

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
        expect(page.get_by_text("请先选择图谱范围", exact=True)).to_be_visible()
        assert not overview_requests, overview_requests
        evidence["checks"].append("91节点时默认页提示选择范围，不请求全部图谱")
        evidence["student_steps"] += ["登录页输入账号", "首次改密跳转", "改密撤销会话后重新登录图谱"]
        page.get_by_role("combobox").first.select_option("CO")
        with page.expect_response(lambda response: "/api/v1/graph/subgraph?course_code=CO&hops=1" in response.url):
            page.get_by_role("button", name="查询图谱").click()
        page.wait_for_url("**/graph/?course_code=CO&hops=1")
        page.wait_for_function("document.querySelector('.graph-canvas')?._cyreg?.cy?.nodes().length === 2")
        canvas = page.locator(".graph-canvas")
        canvas.scroll_into_view_if_needed()
        # Read viewport coordinates after scrolling; Playwright's automatic
        # scrolling during a positioned element click can invalidate the point.
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        position = canvas.evaluate("e => { const p=e._cyreg.cy.getElementById('CO03').renderedPosition(); const r=e.getBoundingClientRect(); return {x:r.x+e.clientLeft+p.x,y:r.y+e.clientTop+p.y}; }")
        page.mouse.click(position["x"], position["y"])
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
        page.goto(base + "/login/")
        login("browser_student", password)
        page.wait_for_url("**/graph/")
        page.goto(base + "/exercise/?node_id=CO03")
        expect(page.locator(".history-item")).to_have_count(1)
        page.goto(base + "/learning/")
        expect(page.locator(".status-row").filter(has_text="CO03")).to_be_visible()
        evidence["checks"].append("学生退出并重新登录后，答题历史仍仅1条且学习状态保留")
        page.get_by_role("button", name="退出", exact=True).click()
        page.wait_for_url("**/login/")
        first_login("browser_teacher")
        evidence["teacher_steps"].append("教师登录并完成首次改密")
        page.get_by_role("link", name="教师验收", exact=True).click()
        page.wait_for_url("**/teacher/acceptance/")
        expect(page.get_by_role("heading", name="内容数量", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="证据分布", exact=True)).to_be_visible()
        evidence["teacher_steps"] += ["访问教师验收页", "查看内容数量", "查看证据分布"]
        page.reload()
        expect(page.get_by_role("heading", name="证据分布", exact=True)).to_be_visible()
        with engine.begin() as conn:
            for edge_id, relation in (("E999001", "contrast"), ("E999002", "boundary")):
                conn.execute(text("INSERT INTO knowledge_edges(edge_id,source_id,target_id,relation_type,mechanism,abc_grade,boundary_note,evidence_status,evidence_summary) VALUES(:id,'CO03','OS02',:relation,'browser test','C','','待补充','browser test')"),
                             {"id": edge_id, "relation": relation})
        page.goto(base + "/graph/?course_code=CO&hops=1")
        page.wait_for_function("document.querySelector('.graph-canvas')?._cyreg?.cy?.edges().length === 3")
        shapes = page.locator(".graph-canvas").evaluate("e => Object.fromEntries(e._cyreg.cy.edges().map(edge => [edge.id(), edge.style('target-arrow-shape')] ))")
        assert shapes == {"E001": "triangle", "E999001": "none", "E999002": "none"}, shapes
        for edge_id in ("E999001", "E999002"):
            expect(page.locator(f'a.edge-card[href="/edge/?id={edge_id}"] strong')).to_have_text("TLB — 虚拟内存")
        evidence["checks"].append("有向关系保留箭头，对比和边界关系图线及关系清单均无单向箭头")
        page.get_by_role("button", name="退出", exact=True).click()
        page.wait_for_url("**/login/")
        evidence["teacher_steps"].append("教师退出")
        assert not errors, errors
        assert not external_requests, sorted(external_requests)
        evidence["application_external_requests"] = sorted(external_requests)
        evidence["checks"].append("本次浏览器学习闭环未向应用源以外发送HTTP请求；不涵盖浏览器自身后台通信")
        evidence["checks"].append("无未处理浏览器脚本异常；刷新保留查询参数和会话")
        evidence["browser_version"] = browser.version
        evidence["mode"] = f"headless {channel}, real exported pages + Nginx + PostgreSQL"
        context.close()
        browser.close()
    engine.dispose()
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
