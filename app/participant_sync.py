"""One intake path for confirmed roster batches and verified masked documents."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import io
import re
from pypdf.errors import PyPdfError

from .insurance_income_match import ManifestError, load_review_manifest, unique_identity_name_match
from .participant_roster import RosterError, mapping_resolver, register_roster
from .rules import trip_region


def document_info(path):
    """Inspect product region and real page coverage locally, without logging text."""
    from pypdf import PdfReader
    path=Path(path)
    if path.stat().st_size > 10*1024*1024:
        raise RosterError('DOCUMENT_TOO_LARGE')
    reader=PdfReader(io.BytesIO(path.read_bytes()))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
        raise RosterError('DOCUMENT_UNREADABLE')
    text='\n'.join(page.extract_text() or '' for page in reader.pages[:2])
    domestic=bool(re.search(r'국내\s*여행|DOMESTIC\s+TRAVEL',text,re.I))
    overseas=bool(re.search(r'해외\s*여행|OVERSEAS\s+TRAVEL',text,re.I))
    return {'region':('KR' if domestic else 'overseas') if domestic != overseas else '',
            'pages':list(range(1,len(reader.pages)+1))}


def prepare_document_batches(review_path, inbox, *, mapping, trips, registered_people=None, trip_overrides=None):
    """Adapt verified documents to the existing immutable roster batch format.

    Only an explicit mapping or a unique enclosing Google trip is sufficient.
    Unresolved periods stay visible as held sources; no invented trip or name.
    """
    review_path, inbox = Path(review_path), Path(inbox)
    normalized = load_review_manifest(review_path)
    raw = review_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != normalized['fingerprint']:
        raise RosterError('SOURCE_CHANGED')
    review = json.loads(raw)
    valid = {trip['tab_id']: trip for trip in trips
             if trip.get('tab_id') in set(mapping.values()) and not trip.get('deleted')}
    reports = []
    for source in review['contracts']:
        key = hashlib.sha256((source['contract_id']+'|'+source['sha256']).encode()).hexdigest()
        batch_id = 'document-' + key[:32]
        base = review_path.parent.resolve()
        pdf = (base / source['source_pdf']).resolve()
        if not pdf.is_relative_to(base) or not pdf.is_file() or pdf.is_symlink():
            reports.append({'source_key': key, 'status': 'rejected', 'code': 'SOURCE_UNAVAILABLE'})
            continue
        if hashlib.sha256(pdf.read_bytes()).hexdigest() != source['sha256']:
            reports.append({'source_key': key, 'status': 'rejected', 'code': 'SOURCE_HASH_MISMATCH'})
            continue
        try:
            info=document_info(pdf)
        except (ImportError, ValueError, OSError, RosterError, PyPdfError):
            reports.append({'source_key':key,'status':'held','code':'DOCUMENT_PRODUCT_UNVERIFIED',
                            'rows':len(source['items'])})
            continue
        if not info['region']:
            reports.append({'source_key':key,'status':'held','code':'DOCUMENT_PRODUCT_UNVERIFIED',
                            'rows':len(source['items'])})
            continue
        overrides=trip_overrides or {}
        tid = overrides.get(key,source.get('cost_trip_id'))
        mapping_basis = 'explicit_source_mapping' if key in overrides else 'explicit_mapping' if tid else 'unique_enclosing_period'
        conflict=False
        if not tid:
            enclosing = [trip for trip in valid.values()
                          if trip.get('starts_on') and trip.get('ends_on')
                          and trip['starts_on'] <= source['travel_start']
                          and source['travel_end'] <= trip['ends_on']]
            candidates=[trip['tab_id'] for trip in enclosing if trip_region(trip)==info['region']]
            conflict=bool(enclosing) and not candidates
            tid = candidates[0] if len(candidates) == 1 else None
        elif tid in valid:
            region=trip_region(valid[tid])
            conflict=bool(region) and region != info['region']
        keys = [k for k, value in mapping.items() if value == tid]
        if conflict or tid not in valid or len(keys) != 1:
            reports.append({'source_key': key, 'status': 'held', 'code': 'TRIP_REGION_CONFLICT' if conflict else 'TRIP_MAPPING_REQUIRED',
                            'rows': len(source['items']), 'period': [source['travel_start'],source['travel_end']]})
            continue
        # The source handoff identifies this already registered contract. Keep
        # its existing participant IDs and links; never register its masks again.
        if source['already_registered']:
            people=(registered_people or {}).get(tid,[])
            matches=[[p['participant_id'] for p in people if item['masked_name']==p.get('display_name')
                      or unique_identity_name_match(item['masked_name'],p.get('display_name',''))]
                     for item in source['items']]
            existing=bool(matches) and all(len(hits)==1 for hits in matches) and len({hits[0] for hits in matches})==len(matches)
            reports.append({'source_key': key, 'status': 'existing_registration' if existing else 'held',
                            'code': '' if existing else 'EXISTING_REGISTRATION_REQUIRED', 'trip_id': tid,
                            'rows': len(source['items'])})
            continue
        batch = inbox / batch_id
        if not batch.resolve().is_relative_to(inbox.resolve()):
            raise RosterError('SOURCE_PATH_INVALID')
        if (batch/'manifest.json').is_file():
            current=json.loads((batch/'manifest.json').read_text(encoding='utf-8'))
            if (current.get('trip_ref') or {}).get('cost_trip_id') != tid:
                reports.append({'source_key':key,'status':'held','code':'EXISTING_MAPPING_PRESERVED'})
                continue
        manifest = {'schema_version': 1, 'batch_id': batch_id,
                    'roster_id': 'insurance-document-'+key[:32], 'revision': 1,
                    'authority': 'verified_insurance_document',
                    'trip_ref': {'cost_trip_id':tid,'google_trip_key':keys[0]},
                    'submitted_by':'verified-insurance-document-adapter',
                    'submitted_at':review['created_at'],
                    'coverage': {'scope':'partial','received_pages':info['pages'],
                                 'expected_pages':len(info['pages']),'declared_people':len(source['items'])},
                    'sources':[{'source_id':'document','path':'sources/document.pdf','sha256':source['sha256']}]}
        items = {'schema_version':1,'items':[
            {'source_item_id':'row-'+hashlib.sha256(item['source_row'].encode()).hexdigest()[:24],
             'source_id':'document','page':None,'row_label':item['source_row'],
             'name':item['masked_name'],'nickname':'','english_name':'',
             'transcription_status':'verified' if item['masked_name'].strip() else 'unreadable'}
            for item in source['items']]}
        if not (batch/'manifest.json').exists():
            (batch/'sources').mkdir(parents=True,exist_ok=True)
            target_pdf = batch/'sources/document.pdf'
            target_items = batch/'participants.json'
            if not all(path.resolve().is_relative_to(batch.resolve()) for path in (target_pdf,target_items)):
                raise RosterError('SOURCE_PATH_INVALID')
            if ((target_pdf.exists() and hashlib.sha256(target_pdf.read_bytes()).hexdigest()!=source['sha256'])
                    or (target_items.exists() and json.loads(target_items.read_text(encoding='utf-8'))!=items)):
                reports.append({'source_key':key,'status':'rejected','code':'DERIVED_BATCH_CONFLICT'})
                continue
            if not target_pdf.exists():
                shutil.copyfile(pdf,target_pdf)
            if not target_items.exists():
                target_items.write_text(json.dumps(items,ensure_ascii=False),encoding='utf-8')
            # Publish the manifest last: the scanner cannot ingest half a batch.
            temporary = batch/'manifest.tmp'
            temporary.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            temporary.replace(batch/'manifest.json')
        reports.append({'source_key':key,'status':'ready','batch_id':batch_id,'trip_id':tid,
                        'rows':len(source['items']),'mapping_basis':mapping_basis})
    return reports


def load_config(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    for key in ('db','inbox','mapping','trip_db'):
        target = Path(value[key])
        if not target.is_absolute():
            raise RosterError('SYNC_CONFIG_PATH_INVALID')
    if '.local-archive' not in Path(value['db']).resolve().parts:
        raise RosterError('SYNC_DB_OUTSIDE_ARCHIVE')
    return value


def sync_once(config, store):
    """Reload the current authority on every cycle; write only participant data."""
    import sqlite3
    actual = Path(store.conn.execute('PRAGMA database_list').fetchone()[2]).resolve()
    if actual != Path(config['db']).resolve():
        raise RosterError('PARTICIPANT_DB_MISMATCH')
    mapping = json.loads(Path(config['mapping']).read_text(encoding='utf-8'))
    connection = sqlite3.connect(Path(config['trip_db']).resolve().as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        trips=[dict(row) for row in connection.execute(
            'SELECT tab_id,destination,starts_on,ends_on,deleted FROM trip_tabs WHERE deleted=0')]
    finally:
        connection.close()
    people={}
    for tid,pid,name in store.conn.execute('SELECT trip_id,participant_id,display_name FROM trip_participants WHERE active=1'):
        people.setdefault(tid,[]).append({'participant_id':pid,'display_name':name})
    try:
        sources = prepare_document_batches(config['review_manifest'],config['inbox'],mapping=mapping,
                                           trips=trips,registered_people=people,
                                           trip_overrides=config.get('document_trip_overrides')) if config.get('review_manifest') else []
    except (ManifestError, OSError, ValueError, RosterError):
        sources = [{'status':'rejected','code':'DOCUMENT_SOURCE_UNAVAILABLE'}]
    batches=scan_inbox(config['inbox'],store,mapping=mapping,expected_web_db=config['db'])
    by_id={batch.get('batch_id'):batch for batch in batches}
    for source in sources:
        if source['status']=='ready' and source.get('batch_id') in by_id:
            source['status']=by_id[source['batch_id']]['status']
    return {'status':'partial' if any(r['status'] in ('held','rejected') for r in sources+batches) else 'ok',
            'sources':sources,'batches':batches,'participant_count':store.conn.execute(
                'SELECT count(*) FROM trip_participants WHERE active=1').fetchone()[0]}


def scan_inbox(inbox, store, *, mapping, expected_web_db=None):
    """Every input format ends in register_roster and the same participant DB."""
    if expected_web_db is not None:
        actual = Path(store.conn.execute('PRAGMA database_list').fetchone()[2]).resolve()
        if actual != Path(expected_web_db).resolve():
            raise RosterError('PARTICIPANT_DB_MISMATCH')
    reports=[]
    for batch in sorted(Path(inbox).iterdir()):
        if not batch.is_dir():
            continue
        if not (batch/'manifest.json').is_file() or not (batch/'participants.json').is_file():
            reports.append({'batch_dir':batch.name,'status':'pending_input'})
            continue
        try:
            result=register_roster(store,batch,trip_resolver=mapping_resolver(mapping))
            reports.append({k:result[k] for k in (
                'batch_id','status','status_reason','reused','trip_id','new_participants',
                'reused_participants') if k in result})
        except RosterError as exc:
            reports.append({'batch_dir':batch.name,'status':'rejected','code':exc.code})
    return reports
