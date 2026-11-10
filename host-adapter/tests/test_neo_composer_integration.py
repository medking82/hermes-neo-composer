"""Exercise Neo RPCs through a real gateway and provider request loop (local model fixture)."""
import asyncio
import base64
import json

import pytest

from tests.gateway.test_session_busy_controls import owner, settled, admissions
from tests.gateway.fixtures.local_recovery_probe import rpc, websocket
from tests.gateway.test_neo_composer_adapter import PNG
from tests.waiting import async_wait_until


@pytest.mark.platforms('linux')
def test_image_steer_reaches_same_provider_turn_and_persists(tmp_path):
    with owner(tmp_path) as (home, peer, desc):
        async def probe():
            async with websocket(home, desc) as ws:
                created = await rpc(ws, 'session.create', request_id='neo-image', source='tui', toolsets=['terminal'])
                assert 'result' in created, created
                sid = created['result']['session_id']
                await rpc(ws, 'prompt.submit', session_id=sid, input_id='warm', text='WARM')
                await settled(home)
                peer.blocked.clear()
                peer.release.clear()
                await rpc(ws, 'prompt.submit', session_id=sid, input_id='active', text='BLOCK_STEER')
                assert await asyncio.to_thread(peer.blocked.wait, 25)
                cap = await rpc(ws, 'neo.composer.capabilities', protocol=1, session_id=sid)
                assert cap.get('result', {}).get('strict_steer'), cap
                generation = cap['result']['execution_generation']
                marker = 'NEO_REAL_IMAGE_CORRECTION'
                params = dict(protocol=1, session_id=sid, request_id='image-1',
                              execution_generation=generation, text=marker,
                              images=[dict(filename='pixel.png', content_base64=base64.b64encode(PNG).decode())],
                              timeout_ms=20000)
                await ws.send(json.dumps(dict(jsonrpc='2.0', id='neo-image-steer', method='neo.composer.steer', params=params)))
                await async_wait_until(lambda: list((home / 'cache' / 'images').glob('*')),
                                       timeout=10, what='actual image staged by gateway')
                peer.release.set()
                async with asyncio.timeout(25):
                    while True:
                        answer = json.loads(await ws.recv())
                        if answer.get('id') == 'neo-image-steer':
                            break
                receipt = answer.get('result', {})
                assert receipt.get('status') == 'delivered', answer
                assert receipt['execution_generation'] == generation
                assert receipt['image_count'] == 1
                await settled(home)
                corrected = [r for r in peer.requests if marker in json.dumps(r.get('messages'))]
                assert corrected, peer.requests
                row = next(m for m in corrected[-1]['messages'] if marker in str(m.get('content')))
                assert row['role'] == 'user' and 'OUT-OF-BAND USER MESSAGE' in row['content']
                assert 'vision_analyze' in row['content']
                assert any(p.read_bytes() == PNG for p in (home / 'cache' / 'images').glob('*'))
                history = await rpc(ws, 'session.resume', session_id=sid)
                assert marker in json.dumps(history['result']['messages'])
                assert [r[0] for r in admissions(home)] == ['warm', 'active']
                stale = await rpc(ws, 'neo.composer.steer', **{**params, 'request_id': 'too-late'})
                assert stale.get('error', {}).get('message') == 'stale_generation', stale
        asyncio.run(probe())
