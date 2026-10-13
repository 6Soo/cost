"""OTA 근거 자료의 위치를 명시적으로 등록한다.

자료를 임의로 훑지 않는다. 기본 경로는 등록 manifest가 없을 때의 기존
동작 그대로 한 곳이고, manifest가 있으면 그 안의 절대 경로만 추가된다.
manifest에 적힌 경로가 없으면 조용히 넘어가지 않는다. 그 사실은 진단으로
남고, 판단은 호출자가 한다.
"""
import hashlib
import json
import os
from pathlib import Path


SCHEMA_VERSION='ota-sources-v1'
MANIFEST_NAME='ota-sources.json'


class OtaSourcesError(RuntimeError):
    """등록 manifest 자체를 읽을 수 없거나 형식이 정본과 다르다."""

    def __init__(self, message, *, code='OTA_SOURCES_INVALID'):
        super().__init__(message)
        self.code=code
        self.message=message


def manifest_path(data_directory):
    """manifest 파일 위치. 환경변수가 있으면 그 파일이 정본이다."""
    configured=os.environ.get('WEBLEDGER_OTA_SOURCES')
    if configured:
        return Path(configured)
    return Path(data_directory)/MANIFEST_NAME


def read_manifest(path, *, required=False):
    """manifest 한 개를 읽는다. 없으면 None, 형식이 다르면 오류."""
    path=Path(path)
    if not path.is_file():
        # 환경변수로 명시한 목록 파일은 없는 그 자체가 오류다. 조용히 기본값으로
        # 내려가면 등록 자료가 빠진 사실을 아무도 몰라.
        if required:
            raise OtaSourcesError(f'OTA 근거 자료 목록 파일이 없습니다: {path}',
                                  code='OTA_SOURCES_MANIFEST_MISSING')
        return None
    try:
        raw=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:
        raise OtaSourcesError(f'OTA 근거 자료 목록을 읽을 수 없습니다: {exc}',
                              code='OTA_SOURCES_UNREADABLE') from None
    if not isinstance(raw,dict) or raw.get('schema_version')!=SCHEMA_VERSION:
        raise OtaSourcesError('OTA 근거 자료 목록의 schema_version이 정본과 다릅니다',
                              code='OTA_SOURCES_SCHEMA_MISMATCH')
    return raw


def content_stamp(path):
    """내용 기준 표식. 크기와 시각이 같아도 내용이 다르면 달라진다."""
    path=Path(path)
    if not path.is_file():
        return None
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda:handle.read(1<<20),b''):
            digest.update(block)
    return {'path':str(path.resolve()),'sha256':digest.hexdigest()}


def mail_stamps(directories):
    """Content stamps of the mail files a directory contributes; the mail parse depends on nothing else."""
    watched = []
    for directory in directories or []:
        path = Path(directory)
        if path.is_dir():
            watched += sorted(path.glob('gmail*.json')) + [path / 'collection.json']
    return tuple(sorted((stamp for stamp in (content_stamp(item) for item in {Path(p) for p in watched})
                         if stamp), key=lambda stamp: stamp['path']))


def source_stamps(sources):
    """Content stamps of every registered source file the OTA reconciliation reads."""
    sources = sources or {}
    watched = [Path(sources['manifest_path'])] if sources.get('manifest_path') else []
    watched += [Path(p) for p in mail_stamps_paths(sources.get('mail_directories'))]
    for database in sources.get('portal_databases') or []:
        watched += [Path(database), Path(str(database) + '-wal')]
    watched += [Path(p) for p in sources.get('reference_documents') or []]
    return tuple(sorted((stamp for stamp in (content_stamp(item) for item in {Path(p) for p in watched})
                         if stamp), key=lambda stamp: stamp['path']))


def mail_stamps_paths(directories):
    paths = []
    for directory in directories or []:
        path = Path(directory)
        if path.is_dir():
            paths += sorted(path.glob('gmail*.json')) + [path / 'collection.json']
    return paths


def manifest_entries(manifest, key):
    """manifest 한 항목은 절대 경로 목록이어야 한다."""
    values=manifest.get(key,[])
    if not isinstance(values,list):
        raise OtaSourcesError(f'{key}는 경로 목록이어야 합니다',
                              code='OTA_SOURCES_SCHEMA_MISMATCH')
    paths=[]
    for value in values:
        if not isinstance(value,str) or not value.strip():
            raise OtaSourcesError(f'{key}에 빈 경로가 있습니다',
                                  code='OTA_SOURCES_SCHEMA_MISMATCH')
        path=Path(value)
        if not path.is_absolute():
            raise OtaSourcesError(f'{key}는 절대 경로만 받습니다: {value}',
                                  code='OTA_SOURCES_RELATIVE_PATH')
        paths.append(path)
    return paths


def _merge(default, registered):
    """기본 경로를 먼저 두고 등록 경로를 덧붙인 뒤 중복을 지운다."""
    merged=[]
    seen=set()
    for path in list(default or [])+list(registered or []):
        path=Path(path)
        key=os.path.normcase(str(path.resolve()))
        if key in seen:
            continue
        seen.add(key)
        merged.append(path)
    return merged


def resolve_sources(data_directory, *, mail_default=None, portal_default=None, manifest_file=None):
    """사용할 메일 디렉터리와 포털 DB 목록을 함께 돌려준다.

    반환값은 관측이다. `missing` 은 등록되어 있는데 없는 경로이고,
    `diagnostics` 는 사람이 읽을 문장이다. 조용히 버리지 않는다.
    """
    path=Path(manifest_file) if manifest_file is not None else manifest_path(data_directory)
    explicit=os.environ.get('WEBLEDGER_OTA_SOURCES') is not None or manifest_file is not None
    manifest=read_manifest(path,required=explicit)
    if manifest is None:
        return {
            'manifest_path':str(path),'manifest_present':False,
            'manifest_stamp':None,
            'mail_directories':[Path(mail_default)] if mail_default is not None else [],
            'portal_databases':[Path(portal_default)] if portal_default is not None else [],
            'reference_documents':[],
            'registered':{'mail_directories':[],'portal_databases':[],
                          'reference_documents':[]},
            'missing':[],'diagnostics':[],
        }
    mails=_merge([Path(mail_default)] if mail_default is not None else [],
                 manifest_entries(manifest,'mail_directories'))
    # With a manifest, the registered list is the authority. A default that is not
    # there (for example a path inside a release folder that has no outputs/) is
    # dropped, so it cannot fail the whole reconciliation. Without a manifest the
    # single previous path stays, and its absence still stops the read.
    portal_fallback=[Path(portal_default)] if portal_default is not None else []
    portal_fallback=[p for p in portal_fallback if p.is_file()]
    portals=_merge(portal_fallback,manifest_entries(manifest,'portal_databases'))
    # 참고 자료는 선택 항목이다. 없으면 빈 목록이고 동작은 그대로다.
    references=manifest_entries(manifest,'reference_documents') if 'reference_documents' in manifest else []
    registered_mails=manifest_entries(manifest,'mail_directories')
    registered_portals=manifest_entries(manifest,'portal_databases')
    missing=[]
    # 기본 경로는 예전처럼 있으면 쓰는 자리이고, 없으면 조용히 비는 자리다.
    # 명시 등록한 경로만 없는 사실 자체가 진단이다.
    registered_mails={str(path.resolve()) for path in manifest_entries(manifest,'mail_directories')}
    registered_portals={str(path.resolve()) for path in manifest_entries(manifest,'portal_databases')}
    for kind,paths,checker in (('mail_directory',mails,lambda p:Path(p).is_dir()),
                               ('portal_database',portals,lambda p:Path(p).is_file()),
                               ('reference_document',references,lambda p:Path(p).is_file())):
        for candidate in paths:
            if checker(candidate):
                continue
            registered=(kind=='reference_document'
                        or str(candidate.resolve()) in registered_mails
                        or str(candidate.resolve()) in registered_portals)
            if registered:
                missing.append({'kind':kind,'path':str(candidate),
                                'registered_in':str(path)})
    diagnostics=[f'등록된 {item["kind"]} 이(가) 없습니다: {item["path"]}' for item in missing]
    return {'manifest_path':str(path),'manifest_present':True,
            'manifest_stamp':manifest_stamp(path),
            'mail_directories':mails,'portal_databases':portals,
            'reference_documents':references,
            'registered':{'mail_directories':registered_mails,
                          'portal_databases':registered_portals,
                          'reference_documents':references},
            'missing':missing,'diagnostics':diagnostics}


def manifest_stamp(path):
    """manifest 자체의 내용 변경을 캐시 지문에서 알아볼 수 있는 표식."""
    return content_stamp(path)
