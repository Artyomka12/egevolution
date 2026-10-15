"""Build an independent JSON-content migration candidate; never modify source.

The destination must not exist. Publication/replacement is deliberately separate
from this exporter, so failed verification cannot affect the original database.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

from core.content_store import TABLES, IDENTITIES, AUTHORS, Store, initialize, digest
from scripts.migrate import statements, check_database, fingerprint, pending_migrations, files, ROOT


def expected_schema(migrations):
    """Read-only schema derivation for auditing a separately built candidate."""
    content = set(sum((list(v) for v in TABLES.values()), []))
    replaced = {'thematic_attempt_insert','test_attempt_insert','test_attempt_finish'}
    with closing(sqlite3.connect(':memory:')) as old:
        old.execute('CREATE TABLE users (id INTEGER PRIMARY KEY)')
        for name,_,chunks in migrations:
            if name == '003_json_content.sql': break
            for sql in chunks: old.execute(sql)
        objects = list(old.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT IN ('users','sqlite_sequence')"))
    expected = {name:sql for kind,name,table,sql in objects if table not in content and name not in replaced}
    for name,_,chunks in migrations:
        if name != '003_json_content.sql': continue
        for sql in chunks:
            clean = re.sub(r'--[^\n]*','',sql).strip().rstrip(';')
            match = re.match(r'CREATE (?:TABLE|TRIGGER) (\w+)',clean)
            if match: expected[match[1]] = clean
    return expected


def build_candidate(source, destination, *, media_source=None):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).resolve()
    if destination.exists() or destination == source.parent or destination.is_relative_to(source.parent):
        raise ValueError('A new isolated destination outside the source project is required')
    if os.environ.get('EGEVOLUTION_CONTENT_ROOT'):
        raise ValueError('Unset EGEVOLUTION_CONTENT_ROOT before offline export')
    # Open read-only, obtain a consistent snapshot without importing the app.
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as original:
        original.execute('BEGIN')
        check_database(original)
        snapshot = sqlite3.connect(':memory:')
        original.backup(snapshot)
    with closing(snapshot):
        check_database(snapshot)
        pending_migrations(snapshot,files(ROOT/'migrations'))
        content_tables = set(sum((list(v) for v in TABLES.values()), []))
        objects = list(snapshot.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name<>'sqlite_sequence'"))
        present = {r[1] for r in objects if r[0]=='table'}
        if not content_tables <= present:
            raise ValueError('Expected complete 001/002 content schema')
        export = {}
        for table in content_tables:
            cursor = snapshot.execute('SELECT * FROM "'+table+'"')
            columns = [c[0] for c in cursor.description]
            export[table] = [dict(zip(columns,row)) for row in cursor]
        preserved = {}
        for table in present-content_tables:
            preserved[table] = snapshot.execute('SELECT * FROM "'+table+'"').fetchall()
        sequences = list(snapshot.execute('SELECT name,seq FROM sqlite_sequence')) if snapshot.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() else []
        replacement = (ROOT/'migrations/003_json_content.sql').read_bytes()
        new_statements = [s for s in statements(replacement.decode('utf-8'))
                          if re.sub(r'--[^\n]*','',s).strip().upper().startswith('CREATE ')]
        replaced_triggers = {'thematic_attempt_insert','test_attempt_insert','test_attempt_finish'}
        destination.mkdir(parents=True)
        database = destination/'users.db'
        with closing(sqlite3.connect(database, isolation_level=None)) as target:
            target.execute('PRAGMA foreign_keys=ON')
            target.execute('BEGIN')
            target.execute('PRAGMA defer_foreign_keys=ON')
            deferred = []
            for kind,name,table,sql in objects:
                if table in content_tables or name in replaced_triggers:
                    continue
                if kind == 'table': target.execute(sql)
                else: deferred.append(sql)
            for sql in new_statements:
                if re.search(r'CREATE TRIGGER',sql): deferred.append(sql)
                else: target.execute(sql)
            stores = [initialize(target,domain,export) for domain in TABLES]
            # Copy identity-only rows before learner rows; actor FK checks deferred.
            for table,columns in IDENTITIES.items():
                for row in export[table]:
                    target.execute('INSERT INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(row.get(c) for c in columns))
            for table,rows in preserved.items():
                if rows:
                    target.executemany('INSERT INTO "'+table+'" VALUES ('+','.join('?' for _ in rows[0])+')',rows)
            for store in stores: store.register()
            for table,sequence in sequences:
                if table not in present-content_tables and table not in IDENTITIES:
                    continue
                current = target.execute('SELECT seq FROM sqlite_sequence WHERE name=?',(table,)).fetchone()
                if current:
                    target.execute('UPDATE sqlite_sequence SET seq=? WHERE name=?',(max(current[0],sequence),table))
                else:
                    target.execute('INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)',(table,sequence))
            # Verify deserialization against every exported source field. Actor
            # attribution is intentionally private; it is not curriculum content.
            for domain in TABLES:
                loaded = Store(target,domain)
                for table in TABLES[domain]:
                    clean = lambda rows: sorted(digest({k:v for k,v in row.items() if k not in AUTHORS}) for row in rows)
                    if clean(export[table]) != clean(loaded.rows(table)):
                        raise ValueError('Export round-trip mismatch: '+table)
            for sql in deferred: target.execute(sql)
            target.execute('INSERT INTO schema_migrations VALUES (?,?,?,?)',
                ('003_json_content.sql',hashlib.sha256(replacement).hexdigest(),time.time_ns()//1000000,'json-content'))
            check_database(target)
            for table,rows in preserved.items():
                actual = target.execute('SELECT * FROM "'+table+'"').fetchall()
                if table == 'schema_migrations': actual = [r for r in actual if r[0]!='003_json_content.sql']
                if sorted(map(repr,rows)) != sorted(map(repr,actual)):
                    raise ValueError('Preserved table mismatch: '+table)
            target.commit()
            check_database(target)
        media_source = Path(media_source or source.parent)
        media_count = 0
        for domain,store in zip(TABLES,stores):
            table = 'thematic_media' if domain=='thematic' else 'test_media'
            for row in export[table]:
                key = row['storage_key']
                if Path(key).name != key or key in ('.','..'):
                    raise ValueError('Unsafe media storage key')
                src = media_source/'data'/domain/'media'/key
                if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=row['sha256']:
                    raise ValueError('Missing or mismatched media')
                store.media_root.mkdir(parents=True,exist_ok=True)
                dst=store.media_root/key
                shutil.copyfile(src,dst)
                if hashlib.sha256(dst.read_bytes()).hexdigest()!=row['sha256']:
                    raise ValueError('Media copy verification failed')
                media_count += 1
        report = {'database':str(database),'media':media_count,
                  'published_thematic':sum(r['state']=='published' for r in export['thematic_variants']),
                  'thematic_versions':len(export['thematic_versions']),
                  'preserved_tables':{t:len(rows) for t,rows in preserved.items()},
                  'integrity_check':'ok','foreign_key_check':[],
                  'source_fingerprint':fingerprint(snapshot)}
        (destination/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    parser.add_argument('--media-source',type=Path)
    args = parser.parse_args()
    report = build_candidate(args.source,args.destination,media_source=args.media_source)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
