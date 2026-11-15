import asyncio
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from runtime.diagnosis.limits import canonical_callback, positive_int
from runtime.diagnosis.worker import DiagnosisWorker
from runtime.diagnosis.routes import DiagnosisRequestSchema


@pytest.mark.parametrize('url', ['http://169.254.169.254/latest/meta-data',
    'http://127.0.0.1:5432/cous/diagnosis/callback', 'http://callback/cous/diagnosis/callback',
    'http://127.0.0.1.evil.test:8000/cous/diagnosis/callback',
    'http://user:password@127.0.0.1:8000/cous/diagnosis/callback',
    'http://127.0.0.1:8000/cous/diagnosis/callback?secret=1',
    'http://127.0.0.2:8000/cous/diagnosis/callback',
    'http://127.0.0.1:8000/cous/diagnosis/callback#fragment'])
def test_callback_cannot_address_arbitrary_host_service_or_credentials(url):
    with pytest.raises(ValueError):canonical_callback(url)


@pytest.mark.parametrize('host', ['localhost', '127.0.0.1', '[::1]'])
def test_callback_pins_localhost_without_dns(host):
    actual = canonical_callback('http://' + host + ':8000/cous/diagnosis/callback')
    assert actual in ('http://127.0.0.1:8000/cous/diagnosis/callback', 'http://[::1]:8000/cous/diagnosis/callback')


@pytest.mark.parametrize('raw', ['0', '-1', 'NaN', '1001'])
def test_invalid_queue_capacity_fails_closed(monkeypatch, raw):
    monkeypatch.setenv('CAPACITY_TEST', raw)
    with pytest.raises(ValueError):positive_int('CAPACITY_TEST', 100, 1000)


def test_oversized_context_is_rejected():
    with pytest.raises(ValueError):
        DiagnosisRequestSchema(correlation_id=uuid4(), capture_session_id=uuid4(), instance_id=uuid4(),
            domain_id=uuid4(), delivery_mode='polling', context={'large':'x'*170000})


class Context:
    def __init__(self, conn):self.conn=conn
    async def __aenter__(self):return self.conn
    async def __aexit__(self,*args):return False


class Connection:
    def __init__(self):self.active=0;self.claim_sizes=[];self.events=[]
    def transaction(self):return Context(self)
    async def execute(self, sql, *args):self.events.append((sql,args))
    async def fetchval(self, sql,*args):return self.active
    async def fetch(self, sql,*args):
        self.claim_sizes.append(args[0])
        rows=[{'id':uuid4()} for _ in range(args[0])]
        self.active+=len(rows)
        return rows


@pytest.mark.anyio
async def test_worker_does_not_claim_more_than_available_slots_and_releases_on_shutdown():
    conn=Connection();repo=SimpleNamespace(_pool=SimpleNamespace(acquire=lambda:Context(conn)))
    worker=DiagnosisWorker(repo,None,max_concurrent=2)
    entered=asyncio.Event()
    async def blocked(row):
        entered.set();await asyncio.Event().wait()
    worker._process_one=blocked
    await worker._process_pending();await entered.wait()
    await worker._process_pending()
    assert conn.claim_sizes==[2] and len(worker._jobs)==2
    await worker.stop()
    assert len(worker._jobs)==0
    assert sum("SET status='pending'" in sql for sql,args in conn.events)==2


@pytest.mark.anyio
async def test_worker_respects_other_process_processing_count():
    conn=Connection();conn.active=2
    worker=DiagnosisWorker(SimpleNamespace(_pool=SimpleNamespace(acquire=lambda:Context(conn))),None,max_concurrent=2)
    await worker._process_pending()
    assert conn.claim_sizes==[] and not worker._jobs


@pytest.mark.anyio
async def test_diagnosis_timeout_becomes_terminal_failure():
    worker=DiagnosisWorker(None,None,max_retries=1,diagnosis_timeout=0.01)
    async def stalled(*args,**kwargs):await asyncio.sleep(10)
    failures=[]
    async def failed(*args):failures.append(args)
    worker._run_diagnosis=stalled;worker._mark_failed=failed
    row=dict(id=uuid4(),capture_session_id=uuid4(),instance_id=uuid4())
    await asyncio.wait_for(worker._process_one(row),timeout=1)
    assert len(failures)==1 and 'TimeoutError' in failures[0][1]


@pytest.mark.anyio
async def test_callback_redirect_does_not_send_payload_to_second_host():
    conn=Connection()
    async def lookup(*args):return {'callback_endpoint':'http://127.0.0.1:8000/cous/diagnosis/callback'}
    conn.fetchrow=lookup
    seen=[]
    async def handler(request):
        seen.append(str(request.url))
        return httpx.Response(307,headers={'location':'http://169.254.169.254/exfiltrate'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=True) as client:
        worker=DiagnosisWorker(SimpleNamespace(_pool=SimpleNamespace(acquire=lambda:Context(conn))),client)
        with pytest.raises(httpx.HTTPStatusError):
            await worker._send_callback(uuid4(),dict(correlation_id='test',capture_session_id='capture',trace_id='trace',hypotheses=[]))
    assert seen==['http://127.0.0.1:8000/cous/diagnosis/callback']
