import json
from uuid import uuid4

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.diagnosis.systemos import create_systemos_router


def envelope():
    return {"schemaVersion":1,"snapshot":{"schemaVersion":1,
        "scope":{"source_system":"systemos","organization_id":str(uuid4()),"service_order_id":str(uuid4())},
        "numeroOS":"1141","evidencias":[{"id":"TESTES","conteudo":"Teste registrado"}]},
        "snapshotHash":"a"*64,"consultadoEm":"2026-10-16T00:00:00Z",
        "prompt":"TAREFA_SYSTEMOS_ANALISE_TECNICA_V2\nTeste registrado",
        "evidenceSet":[],"servicosSugeridos":[]}


def setup(monkeypatch, source=None, *, stale=False):
    source=source or envelope()
    calls=[]
    monkeypatch.setenv("OPENTRACY_COUS_V3_AUTH_TOKEN","test-token")
    monkeypatch.setenv("OPENTRACY_SYSTEMOS_URL","https://systemos.test/api/v1")
    monkeypatch.setenv("OPENTRACY_SYSTEMOS_READ_KEY","r"*64)
    monkeypatch.setenv("OPENTRACY_SYSTEMOS_ORGANIZATION_ID",source["snapshot"]["scope"]["organization_id"])
    async def transport(request):
        calls.append(request)
        assert request.headers["x-cognitive-read-key"]=="r"*64
        if request.method=="GET":
            return httpx.Response(200,json=source)
        payload=json.loads(request.content)
        assert payload["snapshotHash"]==source["snapshotHash"]
        assert payload["resultado"]["achados"][0]["evidencias"]==["TESTES"]
        return httpx.Response(409 if stale else 200,json={"conclusao":"Texto validado na fonte","trechosDescartados":0,"incoerencias":[]})
    async def generate(prompt):
        calls.append(prompt)
        return {"success":True,"response":json.dumps({"achados":[{"texto":"Teste registrado","evidencias":["TESTES"]}]}),"trace_id":"trace"}
    app=FastAPI()
    app.include_router(create_systemos_router(generate,http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport))))
    return TestClient(app),calls,source


def test_live_read_no_capture_or_index_and_validates_at_source(monkeypatch):
    client,calls,source=setup(monkeypatch)
    result=client.post("/v3/systemos/diagnosis",json={"order":"1141"},headers={"authorization":"Bearer test-token"})
    assert result.status_code==200,result.text
    assert result.json()["conclusion"]=="Texto validado na fonte"
    assert "_model_output" not in result.json()
    assert [c.method for c in calls if not isinstance(c,str)]==["GET","POST"]
    assert all("/integracoes/cognicao/ordens/1141" in str(c.url) for c in calls if not isinstance(c,str))


def test_authentication_and_identifier_validation_prevent_fetch(monkeypatch):
    client,calls,_=setup(monkeypatch)
    assert client.post("/v3/systemos/diagnosis",json={"order":"1141"}).status_code==401
    assert client.post("/v3/systemos/diagnosis",json={"order":"../other"},headers={"authorization":"Bearer test-token"}).status_code==422
    assert calls==[]


def test_source_change_refuses_stale_conclusion(monkeypatch):
    client,_,_=setup(monkeypatch,stale=True)
    assert client.post("/v3/systemos/diagnosis",json={"order":"1141"},headers={"authorization":"Bearer test-token"}).status_code==409


def test_wrong_order_never_reaches_model(monkeypatch):
    source=envelope();source["snapshot"]["numeroOS"]="1134"
    client,calls,_=setup(monkeypatch,source)
    assert client.post("/v3/systemos/diagnosis",json={"order":"1141"},headers={"authorization":"Bearer test-token"}).status_code==409
    assert not any(isinstance(c,str) for c in calls)


def test_oversized_context_is_rejected_before_generation(monkeypatch):
    source=envelope();source["prompt"]+="x"*32001
    client,calls,_=setup(monkeypatch,source)
    assert client.post("/v3/systemos/diagnosis",json={"order":"1141"},headers={"authorization":"Bearer test-token"}).status_code==502
    assert not any(isinstance(c,str) for c in calls)


def test_live_path_keeps_empty_frame_barrier_before_scoring(monkeypatch):
    source=envelope()
    relation=[0,3,True,900,900,800,100,125]
    source["evidenceSet"]=[{"evidence_type":"systemos_correlation_timeline", "data":{
        "type":"systemos_correlation_timeline","version":1,"sessao":"initial",
        "data":"2026-10-16T00:00:00Z","tipoColeta":"DESEMPENHO","current_collection":True,
        "catalogo":[["locked_rotor_hypothesis",3,"mpu,power","Confirm independently"]],
        "frames":[["a",1,True,True,True,[relation]],["b",2,True,True,True,[]],
                  ["c",3,True,True,True,[relation]]]}}]
    client,_,_=setup(monkeypatch,source)
    result=client.post("/v3/systemos/diagnosis",json={"order":"1141"},headers={"authorization":"Bearer test-token"})
    assert result.status_code==200,result.text
    mode=next(h for h in result.json()["hypotheses"] if h.get("diagnostic_kind")=="locked_rotor_hypothesis")
    assert mode["persistent"] is False
    assert mode["active_frames"]==2
