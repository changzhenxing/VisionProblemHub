from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from app.main import app
from app.db import engine

client=TestClient(app)
remote=TestClient(app, client=('192.0.2.10', 1234))
assert remote.post('/api/auth/setup',json={'password':'TestPassword123!'}).status_code==403
assert client.post('/api/auth/setup',json={'password':'TestPassword123!'},headers={'Origin':'http://evil.example'}).status_code==403
assert client.post('/api/auth/setup',json={'password':'TestPassword123!'}).status_code==200
ROLE_ID=next(role['id'] for role in client.get('/api/admin/roles').json() if role['name']=='团队成员')

def post_user(name):
    r=client.post('/api/users',json={'name':name,'role_id':ROLE_ID,'password':'TestPassword123!'}); assert r.status_code==200; return r.json()['id']

def setup_base():
    u1=post_user('张三');u2=post_user('李四')
    r=client.post('/api/projects',json={'name':'精密AOI-A','manager_id':u1,'current_stage':'开发验证','planned_completion_date':str(date.today()+timedelta(days=30))})
    assert r.status_code==200
    return u1,u2,r.json()['id']

def make_issue(pid,u1,u2,desc='金线局部反光影响特征提取'):
    r=client.post('/api/issues',json={'project_id':pid,'issue_type':'成像','description':desc,'priority':'紧急重要','status':'待处理','owner_id':u2,
        'planned_close_date':str(date.today()+timedelta(days=3)),'close_standard':'1000张验证无反光漏检','created_by_id':u1})
    assert r.status_code==200, r.text
    return r.json()['id']

def test_full_problem_to_knowledge_flow(tmp_path):
    u1,u2,pid=setup_base(); iid=make_issue(pid,u1,u2)
    # creation attachment
    r=client.post(f'/api/issues/{iid}/creation-attachments',data={'actor_id':u1,'attachment_role':'问题证据'},files=[('files',('before.jpg',b'fakejpg','image/jpeg'))])
    assert r.status_code==200
    # progress
    r=client.post(f'/api/issues/{iid}/events',data={'actor_id':u2,'event_type':'进展反馈','content':'初步定位到环形光入射角造成镜面反射','attachment_role':'问题证据'})
    assert r.status_code==200
    # failed solution with image
    r=client.post(f'/api/issues/{iid}/events',data={'actor_id':u2,'event_type':'解决办法','content':'降低曝光3ms到2ms','outcome':'失败','attachment_role':'方案说明'},files=[('files',('v1.png',b'png','image/png'))])
    assert r.status_code==200
    # success solution
    r=client.post(f'/api/issues/{iid}/events',data={'actor_id':u2,'event_type':'解决办法','content':'增加偏振片并调整光源入射角','outcome':'成功','attachment_role':'方案说明'})
    assert r.status_code==200
    # validation with video
    r=client.post(f'/api/issues/{iid}/events',data={'actor_id':u2,'event_type':'验证结果','content':'连续1000张验证通过，未出现反光导致的漏检','outcome':'成功','attachment_role':'验证证据'},files=[('files',('run.mp4',b'fakevideo','video/mp4'))])
    assert r.status_code==200
    # close
    r=client.patch(f'/api/issues/{iid}',json={'actor_id':u1,'status':'已关闭'}); assert r.status_code==200
    detail=client.get(f'/api/issues/{iid}').json()
    assert detail['retrospective']['final_solution']=='增加偏振片并调整光源入射角'
    assert '降低曝光3ms到2ms' in detail['retrospective']['lessons']
    assert '1000张验证通过' in detail['retrospective']['validation_result']
    assert detail['knowledge']['evidence_count']==3
    assert '增加偏振片' in detail['knowledge']['final_solution']
    assert len(detail['events'])>=6
    assert detail['events'][0]['actor_name']=='管理员'


def test_manual_retro_is_preserved_and_correction_logged():
    # reuse existing first issue
    issues=client.get('/api/issues').json(); iid=issues[0]['id']; users=client.get('/api/users').json(); actor=users[0]['id']
    r=client.patch(f'/api/issues/{iid}/retrospective',json={'actor_id':actor,'values':{'root_cause':'人工确认：金线镜面反射与入射角、偏振状态共同相关'},'confirm':True})
    assert r.status_code==200 and r.json()['confirmed']
    # add later progress and regenerate (non-force) should keep manual correction
    client.post(f'/api/issues/{iid}/events',data={'actor_id':actor,'event_type':'进展反馈','content':'补充现场验证，产品姿态变化下仍稳定','attachment_role':'其他'})
    r=client.post(f'/api/issues/{iid}/retrospective/regenerate')
    assert r.json()['root_cause'].startswith('人工确认')
    detail=client.get(f'/api/issues/{iid}').json()
    assert any(e['event_type']=='复盘人工修订' for e in detail['events'])
    assert detail['knowledge']['confidence_state']=='人工确认'


def test_meaningful_change_logging_and_no_noise():
    i=client.get('/api/issues').json()[0]; iid=i['id']; actor=client.get('/api/users').json()[0]['id']
    before=len(client.get(f'/api/issues/{iid}').json()['events'])
    r=client.patch(f'/api/issues/{iid}',json={'actor_id':actor,'priority':i['priority']}); assert r.json()['meaningful_changes']==0
    same=len(client.get(f'/api/issues/{iid}').json()['events']); assert same==before
    r=client.patch(f'/api/issues/{iid}',json={'actor_id':actor,'priority':'一般','planned_close_date':str(date.today()+timedelta(days=10))}); assert r.json()['meaningful_changes']==2
    d=client.get(f'/api/issues/{iid}').json(); types=[e['event_type'] for e in d['events']]
    assert '优先级变化' in types and '计划时间变化' in types


def test_project_retro_stats_and_agent_export():
    p=client.get('/api/projects').json()[0]
    r=client.get(f"/api/projects/{p['id']}/retrospective"); assert r.status_code==200
    txt=r.json()['retrospective']['summary']; assert '问题' in txt and '延期率' in txt
    s=client.get('/api/stats?days=30').json(); assert s['summary']['total']>=1 and s['types']
    k=client.get('/api/knowledge').json(); assert len(k)>=1
    ex=client.get('/api/knowledge/export/agent'); assert ex.status_code==200 and len(ex.json())>=1


def test_concurrent_issue_creation():
    users=client.get('/api/users').json(); projects=client.get('/api/projects').json(); u1=users[0]['id'];u2=users[1]['id'];pid=projects[0]['id']
    def one(n):
        r=client.post('/api/issues',json={'project_id':pid,'issue_type':'算法','description':f'并发测试问题{n}','priority':'一般','status':'待处理','owner_id':u2,'planned_close_date':str(date.today()+timedelta(days=5)),'created_by_id':u1})
        return r.status_code
    with ThreadPoolExecutor(max_workers=10) as ex:
        codes=list(ex.map(one,range(30)))
    assert codes.count(200)==30


def test_sqlite_wal():
    with engine.connect() as c:
        mode=c.exec_driver_sql('PRAGMA journal_mode').scalar()
    assert str(mode).lower()=='wal'

def test_project_meaningful_history_and_auto_issue_status():
    p=client.get('/api/projects').json()[0]; users=client.get('/api/users').json(); actor=users[0]['id']
    d=client.get(f"/api/projects/{p['id']}").json(); before=len(d['events'])
    # same stage should not add history; changed stage and date should
    r=client.patch(f"/api/projects/{p['id']}",json={'current_stage':'现场验证','planned_completion_date':str(date.today()+timedelta(days=40))})
    assert r.status_code==200 and r.json()['meaningful_changes']==2
    d=client.get(f"/api/projects/{p['id']}").json(); assert len(d['events'])==before+2
    # new issue becomes processing after first progress event
    iid=make_issue(p['id'],actor,users[1]['id'],'自动状态推进测试')
    client.post(f'/api/issues/{iid}/events',data={'actor_id':actor,'event_type':'进展反馈','content':'已开始分析','attachment_role':'问题证据'})
    detail=client.get(f'/api/issues/{iid}').json(); assert detail['status']=='处理中'
    assert any((e['metadata'] or {}).get('automatic') for e in detail['events'] if e['event_type']=='状态变化')


def test_attachment_is_served_and_knowledge_manual_lock_survives_regeneration():
    issues=client.get('/api/issues').json(); actor=client.get('/api/users').json()[0]['id']
    detail=None; att=None
    for x in issues:
        d=client.get(f"/api/issues/{x['id']}").json()
        found=[a for e in d['events'] for a in e['attachments']]
        if found:
            detail=d; att=found[0]; break
    assert detail is not None and att is not None
    r=client.get(att['url']); assert r.status_code==200
    kid=detail['knowledge']['id']
    r=client.patch(f'/api/knowledge/{kid}',json={'actor_id':actor,'values':{'applicability':'适用于高反金属表面；低反射漫反射表面需重新验证','confidence_state':'人工确认'}})
    assert r.status_code==200
    client.post(f'/api/knowledge/{kid}/regenerate')
    k=client.get(f'/api/knowledge/{kid}').json(); assert k['applicability'].startswith('适用于高反') and k['confidence_state']=='人工确认'


def test_login_and_role_permissions():
    guest=TestClient(app)
    assert guest.get('/api/projects').status_code==401
    assert guest.get('/api/admin/users').status_code==401
    assert guest.get('/uploads/anything').status_code==401
    assert guest.post('/api/auth/login',json={'name':'管理员','password':'wrong'}).status_code==401
    assert guest.post('/api/auth/login',json={'name':'管理员','password':'TestPassword123!'},headers={'Origin':'http://evil.example'}).status_code==403

    roles=client.get('/api/admin/roles').json()
    viewer_role=next(role for role in roles if role['name']=='只读成员')
    created=client.post('/api/users',json={'name':'只读测试员','role_id':viewer_role['id'],'password':'ViewerPassword123!'})
    assert created.status_code==200
    viewer_id=created.json()['id']
    assert guest.post('/api/auth/login',json={'name':'只读测试员','password':'ViewerPassword123!'}).status_code==200
    assert guest.get('/api/projects').status_code==200
    assert guest.get('/api/admin/roles').status_code==403
    assert guest.post('/api/issues',json={}).status_code==403
    assert guest.post('/api/projects',json={}).status_code==403
    assert guest.patch('/api/knowledge/1',json={}).status_code==403
    assert guest.post('/api/users',json={}).status_code==403

    role=client.post('/api/admin/roles',json={'name':'项目观察员','description':'审阅项目','permissions':[]})
    assert role.status_code==200
    role_id=role.json()['id']
    observer=client.post('/api/users',json={'name':'观察员','role_id':role_id,'password':'ObserverPassword123!'})
    assert observer.status_code==200
    assert client.delete(f'/api/admin/roles/{role_id}').status_code==409
    observer_client=TestClient(app)
    assert observer_client.post('/api/auth/login',json={'name':'观察员','password':'ObserverPassword123!'}).status_code==200
    assert observer_client.post('/api/issues',json={}).status_code==403
    assert client.patch(f'/api/admin/roles/{role_id}',json={'name':'项目观察员','description':'可处理问题','permissions':['issues.write']}).status_code==200
    assert observer_client.post('/api/issues',json={}).status_code!=403
    member_role=next(role for role in roles if role['name']=='团队成员')
    assert client.patch(f"/api/admin/users/{observer.json()['id']}",json={'role_id':member_role['id']}).status_code==200
    assert client.delete(f'/api/admin/roles/{role_id}').status_code==200
    assert observer_client.post('/api/auth/logout').status_code==200
    assert observer_client.get('/api/projects').status_code==401
    assert client.delete(f"/api/admin/roles/{viewer_role['id']}").status_code==400
    assert client.patch(f'/api/admin/users/{viewer_id}',json={'active':False}).status_code==200
    assert guest.get('/api/projects').status_code==401
    assert guest.post('/api/auth/login',json={'name':'只读测试员','password':'ViewerPassword123!'}).status_code==401
    assert client.patch('/api/admin/users/1',json={'active':False}).status_code==400
    assert client.post('/api/admin/roles',json={'name':'坏角色','permissions':[{}]}).status_code==400
    reset=client.post('/api/users',json={'name':'重置测试员','role_id':viewer_role['id'],'password':'OldPassword123!'})
    reset_client=TestClient(app)
    assert reset_client.post('/api/auth/login',json={'name':'重置测试员','password':'OldPassword123!'}).status_code==200
    assert client.patch(f"/api/admin/users/{reset.json()['id']}",json={'password':'NewPassword123!'}).status_code==200
    assert reset_client.get('/api/projects').status_code==401
    assert reset_client.post('/api/auth/login',json={'name':'重置测试员','password':'OldPassword123!'}).status_code==401
    assert reset_client.post('/api/auth/login',json={'name':'重置测试员','password':'NewPassword123!'}).status_code==200
    second_session=TestClient(app)
    assert second_session.post('/api/auth/login',json={'name':'重置测试员','password':'NewPassword123!'}).status_code==200
    assert reset_client.post('/api/auth/password',json={'current_password':'wrong','new_password':'LastPassword123!'}).status_code==400
    assert reset_client.post('/api/auth/password',json={'current_password':'NewPassword123!','new_password':'LastPassword123!'}).status_code==200
    assert reset_client.get('/api/projects').status_code==200
    assert second_session.get('/api/projects').status_code==401


def test_management_feedback_people_and_scope():
    roles = client.get('/api/admin/roles').json()
    member = next(role for role in roles if role['name'] == '团队成员')
    supervisor = next(role for role in roles if role['name'] == '团队主管')
    dept = client.post('/api/org/departments', json={'name': '视觉研发'}).json()
    team = client.post('/api/org/teams', json={'name': '成像组', 'department_id': dept['id']}).json()
    boss = client.post('/api/users', json={'name': '测试主管', 'role_id': supervisor['id'],
                    'team_id': team['id'], 'scope': 'team', 'password': 'SupervisorPassword123!'}).json()
    worker = client.post('/api/users', json={'name': '测试工程师', 'role_id': member['id'],
                      'team_id': team['id'], 'password': 'EngineerPassword123!'}).json()
    outsider = client.post('/api/users', json={'name': '外部测试员', 'role_id': member['id'],
                        'password': 'OutsidePassword123!'}).json()
    project = client.post('/api/projects', json={'name': '权限验收项目', 'manager_id': boss['id'],
                         'current_stage': '开发验证', 'planned_completion_date': str(date.today()+timedelta(days=20))}).json()
    iid = client.post('/api/issues', json={'project_id': project['id'], 'issue_type': '成像',
         'description': '测试条纹反光及低对比度', 'priority': '紧急重要', 'status': '待处理',
         'owner_id': worker['id'], 'planned_close_date': str(date.today()+timedelta(days=3)),
         'created_by_id': boss['id']}).json()['id']
    manager_session = TestClient(app)
    worker_session = TestClient(app)
    outsider_session = TestClient(app)
    assert manager_session.post('/api/auth/login', json={'name': '测试主管', 'password': 'SupervisorPassword123!'}).status_code == 200
    assert worker_session.post('/api/auth/login', json={'name': '测试工程师', 'password': 'EngineerPassword123!'}).status_code == 200
    assert outsider_session.post('/api/auth/login', json={'name': '外部测试员', 'password': 'OutsidePassword123!'}).status_code == 200
    assert outsider_session.get(f'/api/issues/{iid}').status_code == 404
    assert all(item['id'] != iid for item in outsider_session.get('/api/issues').json())
    new_issue = {'project_id': project['id'], 'issue_type': '成像', 'description': '同项目新的反光验证',
                 'priority': '一般', 'status': '待处理', 'owner_id': worker['id'],
                 'planned_close_date': str(date.today()+timedelta(days=5)), 'created_by_id': worker['id']}
    assert outsider_session.post('/api/issues', json=new_issue).status_code == 403
    assert worker_session.post('/api/issues', json=new_issue).status_code == 200
    viewer = next(role for role in roles if role['name'] == '只读成员')
    assert client.put(f'/api/admin/users/{outsider["id"]}/roles', json=[
        {'role_id': member['id'], 'scope': 'self', 'scope_id': None},
        {'role_id': viewer['id'], 'scope': 'project', 'scope_id': project['id']},
    ]).status_code == 200
    assert outsider_session.get(f'/api/issues/{iid}').status_code == 200
    assert outsider_session.post('/api/issues', json=new_issue).status_code == 403
    assert client.put('/api/admin/users/1/roles', json=[
        {'role_id': viewer['id'], 'scope': 'all', 'scope_id': None}]).status_code == 400
    assert outsider_session.get('/api/people').json() == [next(item for item in outsider_session.get('/api/people').json() if item['id'] == outsider['id'])]
    assert manager_session.get(f'/api/issues/{iid}').status_code == 200
    assert manager_session.post(f'/api/projects/{project["id"]}/milestones', json={
        'title': '三批次验证', 'due_date': str(date.today()+timedelta(days=7))}).status_code == 200
    note = manager_session.post(f'/api/people/{worker["id"]}/one-on-ones', json={
        'summary': '确认成像资源', 'growth_goal': '独立负责下一阶段成像方案'}).json()
    assert note['confirmed_at'] is None
    assert outsider_session.get(f'/api/people/{worker["id"]}/one-on-ones').status_code == 404
    assert worker_session.post(f'/api/one-on-ones/{note["id"]}/confirm').status_code == 200
    assert worker_session.get(f'/api/people/{worker["id"]}/growth-actions').json()[0]['title'] == '独立负责下一阶段成像方案'
    result = manager_session.post(f'/api/issues/{iid}/feedback', data={
        'kind': '协助', 'content': '协调光学资源进行三批次验证', 'recipient_id': worker['id'],
        'visibility': 'self_manager'}, files=[('files', ('plan.txt', b'private plan', 'text/plain'))])
    assert result.status_code == 200, result.text
    attachment = result.json()['attachments'][0]['url']
    assert worker_session.get(attachment).status_code == 200
    assert outsider_session.get(attachment).status_code == 404
    assert worker_session.get('/api/notifications').json()
    assert manager_session.post(f'/api/issues/{iid}/decisions', json={
        'fact': '条纹反光', 'decision': '采用偏振加分区曝光', 'commitment': '完成三批次验证',
        'owner_id': worker['id'], 'due_date': str(date.today()+timedelta(days=7))}).status_code == 200
    assert worker_session.get(f'/api/issues/{iid}/decisions').json()[0]['fact'] == '条纹反光'
    report = worker_session.get('/api/reports/weekly').json()
    assert worker_session.put('/api/reports/weekly', json={'week_start': report['week_start'],
         'content': report['content']+'\n本周结论', 'confirm': True}).status_code == 200
    assert worker_session.get('/api/reports/weekly').json()['confirmed_at']
    assert manager_session.get('/api/management/overview').status_code == 200


def test_agent_model_tools_scope_and_confirmed_write(monkeypatch):
    import json
    from app import agent
    from app.db import SessionLocal
    from app.models import AgentModel

    issue = client.get('/api/issues').json()[0]
    iid = issue['id']
    config = {'name': '验证模型', 'base_url': 'https://model.example/v1',
              'model_name': 'test-tool-model', 'api_key': 'test-only-secret', 'is_active': True}
    assert client.post('/api/agent/models', json=config).status_code == 200
    listing = client.get('/api/agent/models').json()
    assert listing[0]['has_api_key'] and 'api_key' not in listing[0]
    with SessionLocal() as db:
        stored = db.get(AgentModel, listing[0]['id'])
        assert 'test-only-secret' not in stored.api_key_encrypted
    assert client.get('/api/agent/status').json()['configured']

    def scripted(*replies):
        responses = iter(replies)
        monkeypatch.setattr(agent, '_chat_completion', lambda *args, **kwargs: next(responses))

    search_call = {'id': 'call_search', 'type': 'function', 'function': {
        'name': 'search_issues', 'arguments': json.dumps({'query': issue['description'][:8]}, ensure_ascii=False)}}
    scripted({'content': None, 'tool_calls': [search_call]}, {'content': '已找到相关问题。'})
    answer = client.post('/api/agent/chat', json={'message': '查找反光问题'}).json()
    assert any(source['id'] == iid for source in answer['message']['sources'])
    conversation_id = answer['conversation_id']
    assert client.get(f'/api/agent/conversations/{conversation_id}').json()['messages'][-1]['trace'][0]['tool'] == 'search_issues'

    viewer_role = next(role for role in client.get('/api/admin/roles').json() if role['name'] == '只读成员')
    assert client.post('/api/users', json={'name': 'Agent无权用户', 'role_id': viewer_role['id'],
                                            'password': 'ViewerPassword123!'}).status_code == 200
    viewer = TestClient(app)
    assert viewer.post('/api/auth/login', json={'name': 'Agent无权用户', 'password': 'ViewerPassword123!'}).status_code == 200
    assert viewer.get('/api/agent/models').status_code == 403
    assert viewer.get(f'/api/agent/conversations/{conversation_id}').status_code == 404
    scripted({'content': None, 'tool_calls': [search_call]}, {'content': '没有可见记录。'})
    restricted = viewer.post('/api/agent/chat', json={'message': '查找反光问题'}).json()
    assert restricted['message']['sources'] == []

    before = len(client.get(f'/api/issues/{iid}').json()['events'])
    draft_call = {'id': 'call_draft', 'type': 'function', 'function': {
        'name': 'draft_issue_event', 'arguments': json.dumps({'issue_id': iid, 'event_type': '进展反馈',
                                                              'content': 'Agent起草待确认的验证进展'}, ensure_ascii=False)}}
    scripted({'content': None, 'tool_calls': [draft_call]}, {'content': '已起草，等待确认。'})
    drafted = client.post('/api/agent/chat', json={'message': '起草一条问题进展'}).json()
    action = drafted['message']['actions'][0]
    assert action['status'] == 'pending'
    assert len(client.get(f'/api/issues/{iid}').json()['events']) == before
    assert viewer.post(f'/api/agent/actions/{action["id"]}/apply').status_code == 404
    assert client.post(f'/api/agent/actions/{action["id"]}/apply').status_code == 200
    assert len(client.get(f'/api/issues/{iid}').json()['events']) == before + 1
    assert client.post(f'/api/agent/actions/{action["id"]}/apply').status_code == 409


def test_agent_provider_request_and_url_validation(monkeypatch):
    import json
    from app import agent
    from app.db import SessionLocal
    from app.models import AgentModel

    assert client.post('/api/agent/models', json={
        'name': '不安全地址', 'base_url': 'http://remote.example/v1', 'model_name': 'x'}).status_code == 400
    observed = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit):
            return b'{"choices":[{"message":{"role":"assistant","content":"ok"}}]}'

    class Opener:
        def open(self, request, timeout):
            observed['url'] = request.full_url
            observed['body'] = json.loads(request.data)
            observed['auth'] = request.get_header('Authorization')
            observed['timeout'] = timeout
            return Response()

    monkeypatch.setattr(agent.urllib.request, 'build_opener', lambda handler: Opener())
    with SessionLocal() as db:
        model = db.get(AgentModel, client.get('/api/agent/models').json()[0]['id'])
        result = agent._chat_completion(model, [{'role': 'user', 'content': 'ping'}], agent.TOOLS[:1])
    assert result['content'] == 'ok'
    assert observed['url'] == 'https://model.example/v1/chat/completions'
    assert observed['body']['tools'][0]['function']['name'] == 'get_my_workbench'
    assert observed['body']['messages'][0]['content'] == 'ping'
    assert observed['auth'] == 'Bearer test-only-secret'
    assert observed['timeout'] == 35
