"""Real timeline query on connection-local tables only; no operational writes."""
import asyncio
import json
import os
from uuid import uuid4
import asyncpg
import httpx
from types import SimpleNamespace
from runtime.diagnosis.worker import DiagnosisWorker
import pytest
from runtime.diagnosis.electromechanical import CORRELATION_TIMELINE_QUERY, summarize_persisted_relations

@pytest.mark.skipif(os.environ.get("OPENTRACY_RUN_DB_TESTS") != "1", reason="temporary PostgreSQL test opt-in")
def test_real_query_preserves_empty_invalid_unknown_frames_and_capture_scope():
    asyncio.run(_run())

async def _run():
    c = await asyncpg.connect(os.environ["OPENTRACY_KNOWLEDGE_DATABASE_URL"])
    try:
        await c.execute("SET search_path TO pg_temp")
        await c.execute("""
          CREATE TEMP TABLE electromechanical_signatures_default(id bigint,capture_session_id uuid);
          CREATE TEMP TABLE signature_deviations(signature_id bigint);
          CREATE TEMP TABLE measurement_sessions(id uuid, capture_session_id uuid);
          CREATE TEMP TABLE measurement_snapshots(id uuid,session_id uuid,type text,timestamp_us bigint,status text,data jsonb,created_at timestamptz default now());
          CREATE TEMP TABLE electromechanical_correlation_relations(snapshot_id uuid,capture_session_id uuid,relation_index int,relation_id text,layer int,assessment int,observed double precision,reference double precision,residual double precision,error_permille int,confidence_permille int,source_channels text,limitation text,valid boolean);
        """)
        capture, session, other = uuid4(), uuid4(), uuid4()
        await c.execute("INSERT INTO measurement_sessions VALUES($1,$2)",session,capture)
        for t in (1,2,3,4):
            snapshot=uuid4()
            data={"version":4,"valid":t!=4,"closure":{"motor":{"rpm_observation_valid":True,"rpm_power_coherent":True}}}
            await c.execute("INSERT INTO measurement_snapshots(id,session_id,type,timestamp_us,status,data) VALUES($1,$2,'electromechanical_correlation_frame',$3,'valid',$4::jsonb)",snapshot,session,t*1000000,json.dumps(data))
            if t!=2:
                await c.execute("INSERT INTO electromechanical_correlation_relations VALUES($1,$2,0,'locked_rotor_hypothesis',3,3,900,800,100,125,900,'mpu,power','test',true)",snapshot,capture)
            if t==2:
                await c.execute("INSERT INTO electromechanical_correlation_relations VALUES($1,$2,0,'unknown_mode',0,0,0,0,0,0,0,'','',true)",snapshot,capture)
        class Acquire:
            async def __aenter__(self): return c
            async def __aexit__(self, *args): return False
        class Pool:
            def acquire(self): return Acquire()
        async with httpx.AsyncClient() as client:
            worker=DiagnosisWorker(SimpleNamespace(_pool=Pool()),client)
            collected=await worker._collect_evidences(capture)
        assert collected[0]['count']==4
        assert collected[0]['diagnostic_modes'][0]['persistent'] is False
        rows=await c.fetch(CORRELATION_TIMELINE_QUERY,str(capture),5000)
        assert len({r['snapshot_id'] for r in rows})==4
        mode=summarize_persisted_relations([dict(r) for r in rows])[0]
        assert mode['max_consecutive_frames']==1
        assert mode['persistent'] is False and mode['active_now'] is False
        assert not await c.fetch(CORRELATION_TIMELINE_QUERY,str(other),5000)
        recent=await c.fetch(CORRELATION_TIMELINE_QUERY,str(capture),2)
        assert len({r['snapshot_id'] for r in recent})==2
        # Historical V4 default zero without RPM flags cannot regain rotor lock.
        await c.execute("UPDATE measurement_snapshots SET data=data#-' {closure,motor,rpm_observation_valid}'::text[]")
        rows=await c.fetch(CORRELATION_TIMELINE_QUERY,str(capture),5000)
        assert summarize_persisted_relations([dict(r) for r in rows])==[]
    finally:
        await c.close()
