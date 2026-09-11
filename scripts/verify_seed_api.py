"""Read-only smoke test through FastAPI routes against the configured database."""
import asyncio
import httpx
from app.main import app
from app.config import get_settings
from app.database import engine
from app.redis_client import _pool
from scripts.seed.go360_data import EVENTS

async def main():
    engine.echo = False
    prefix = get_settings().api_v1_prefix
    checked = 0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://seed-check') as client:
        response = await client.get(prefix + '/event-categories/main')
        response.raise_for_status()
        categories = response.json()
        response = await client.get(prefix + '/events')
        response.raise_for_status()
        assert {e['name'] for e in response.json()} >= {spec[3] for spec in EVENTS}
        for _, main_name, topic, title, *_ in EVENTS:
            root = next(c for c in categories if c['name'] == main_name)
            sub = next(c for c in root['sub_categories'] if c['name'] == topic)
            params = {'main_category_id': root['id'], 'sub_category_id': sub['id']}
            mobile = await client.get(prefix + '/events', params=params)
            mobile.raise_for_status()
            assert title in {e['name'] for e in mobile.json()}
            console = await client.get(prefix + '/events', params={**params, 'page': 1, 'page_size': 100})
            console.raise_for_status()
            assert {e['id'] for e in mobile.json()} == {e['id'] for e in console.json()['items']}
            for event in mobile.json():
                assert event['main_category_id'] == root['id'] and event['sub_category_id'] == sub['id']
            checked += 1
    print(f'PASS: {checked} event mappings through mobile list and console pagination API shapes')
    await _pool.disconnect()
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
