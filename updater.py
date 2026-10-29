"""Full verified Nobel snapshot; optional cached Wikidata enrichment."""
import argparse
from datetime import datetime, timezone, timedelta
import json
import logging
import os
from pathlib import Path
from nobel.sources import NobelClient, WikidataClient, timed
from nobel.storage import DatabaseRepository, utcnow, city_qid

log = logging.getLogger(__name__)

class UpdateLock:
    def __init__(self, db):
        self.path = Path(str(db) + '.lock')
    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise RuntimeError(f'Another update may be active: {self.path}') from None
        os.write(self.fd, str(os.getpid()).encode()); return self
    def __exit__(self, *exc):
        os.close(self.fd); self.path.unlink(missing_ok=True)

class IngestionPipeline:
    def __init__(self, repository, source=None, wikidata=None):
        self.repository = repository
        self.source = source or NobelClient()
        self.wikidata = wikidata or WikidataClient()
    def enrich(self, snapshots, cache, ttl_days):
        if not os.getenv('NOBEL_USER_AGENT'):
            raise ValueError('Set NOBEL_USER_AGENT with your project URL or contact before using Wikidata')
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        def refresh(ids):
            pending = [q for q in sorted(set(filter(None, ids)))
                       if q not in cache or datetime.fromisoformat(cache[q]['fetched_at']) < cutoff]
            result = self.wikidata.fetch(pending)
            for q, entity in result.items():
                cache[q] = {'data': entity, 'fetched_at': utcnow()}
        laureates = snapshots['laureates']['items']
        roots = [l.get('wikidata', {}).get('id') for l in laureates]
        refresh(roots)
        linked = set()
        # One bounded hop; all statements/qualifiers/references of each fetched entity are retained.
        for qid in roots:
            for prop in ('P19', 'P20', 'P69', 'P108', 'P27', 'P106', 'P101'):
                for claim in cache.get(qid, {}).get('data', {}).get('claims', {}).get(prop, []):
                    if claim.get('rank') != 'deprecated':
                        value = claim.get('mainsnak', {}).get('datavalue', {}).get('value', {})
                        if isinstance(value, dict) and 'id' in value:
                            linked.add(value['id'])
        for l in laureates:
            places = [l.get(k, {}).get('place', {}) for k in ('birth', 'death', 'founded')]
            places += [a for p in l.get('nobelPrizes', []) for k in ('affiliations', 'residences') for a in p.get(k, [])]
            linked.update(q for p in places if (q := city_qid(p)))
        refresh(linked)
        return cache
    @timed
    def run(self, snapshot_dir=None, enrich=False, ttl_days=90, allow_count_decrease=False):
        with UpdateLock(self.repository.path):
            snapshots = {}
            for endpoint in ('laureates', 'nobelPrizes'):
                snapshots[endpoint] = (json.loads((Path(snapshot_dir) / f'{endpoint}.json').read_text(encoding='utf-8'))
                    if snapshot_dir else self.source.fetch(endpoint))
            cache = self.repository.wikidata_cache()
            if enrich:
                cache = self.enrich(snapshots, cache, ttl_days)
            changed = self.repository.install(snapshots, cache, allow_count_decrease)
            log.info('Database %s. %s', 'updated' if changed else 'unchanged', self.repository.metadata())
            return changed

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(Path(__file__).with_name('nobel_database.sqlite')))
    parser.add_argument('--snapshot-dir', help='Offline JSON envelopes {items,pages}; useful for reproducible imports')
    parser.add_argument('--wikidata', action='store_true', help='Optional bounded Wikidata enrichment')
    parser.add_argument('--wikidata-ttl-days', type=int, default=90)
    parser.add_argument('--allow-count-decrease', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.wikidata_ttl_days < 1:
        parser.error('TTL must be >= 1 day')
    try:
        IngestionPipeline(DatabaseRepository(args.db)).run(args.snapshot_dir, args.wikidata,
            args.wikidata_ttl_days, args.allow_count_decrease)
    except Exception:
        log.exception('Update failed. Existing database was preserved.')
        raise SystemExit(1)

if __name__ == '__main__':
    main()
