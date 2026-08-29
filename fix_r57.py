import pathlib, re
p = pathlib.Path('ledger/domain/direct_trip_airfare_atomic_admission.py')
text = p.read_text(encoding='utf-8')
# add import if not present
if 'posix_publication' not in text:
    text = text.replace(
        'from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT',
        'from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT\nfrom ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace_at, identity as posix_identity'
    )
# _secure_read
text = re.sub(
    r'flags=os\.O_RDONLY\|getattr\(os,"O_NOFOLLOW",0\)\|getattr\(os,"O_CLOEXEC",0\)\n try:fd=os\.open\(path,flags\)',
    'try:fd=open_nofollow(path)', text
)
# fix flags remain line already handled
text = text.replace(
    '  before=os.fstat(fd)\n   if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1 or stat.S_IMODE(before.st_mode) not in {0o600,0o644}:raise ValueError("r57_manual_file_invalid")',
    '  before=os.fstat(fd)\n   verify_regular_single_link(fd)\n   if before.st_uid!=os.getuid() or stat.S_IMODE(before.st_mode) not in {0o600,0o644}:raise ValueError("r57_manual_file_invalid")'
)
# fix after line: split
text = text.replace(
    '   after=os.fstat(fd);ident=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_mode,x.st_uid,x.st_nlink)\n   if ident(before)!=ident(after):raise ValueError("r57_manual_changed_during_read")',
    '   after=os.fstat(fd)\n   if posix_identity(before)!=posix_identity(after):raise ValueError("r57_manual_changed_during_read")'
)
text = text.replace(' try:check=os.open(path,flags)', ' try:check=open_nofollow(path)')
text = text.replace('  if ident(os.fstat(check))!=ident(before):raise ValueError("r57_manual_identity_changed")', '  if posix_identity(os.fstat(check))!=posix_identity(before):raise ValueError("r57_manual_identity_changed")')

# _capture_dirfd
text = text.replace(
    ' result={};identity=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_ctime_ns,x.st_mode,x.st_uid,x.st_nlink)\n for name in FILES:\n  try:fd=os.open(name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),dir_fd=dfd)',
    ' result={}\n for name in FILES:\n  try:fd=open_at(dfd, name)'
)
text = text.replace(
    '   before=os.fstat(fd)\n    if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600:raise ValueError("r57_package_file_invalid")',
    '   verify_regular_single_link(fd, mode=0o600)\n    before=os.fstat(fd)\n    if before.st_uid!=os.getuid():raise ValueError("r57_package_file_invalid")'
)
text = text.replace(
    '    if identity(before)!=identity(os.fstat(fd)):raise ValueError("r57_package_changed_during_read")',
    '    if posix_identity(before)!=posix_identity(os.fstat(fd)):raise ValueError("r57_package_changed_during_read")'
)
# _capture
text = text.replace(' try:dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))', ' try:dfd=open_dir(directory)')

# build
text = text.replace(' pfd=os.open(out.parent,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0));parent_id=r55.r45._identity(os.fstat(pfd))', ' pfd=open_dir(out.parent);parent_id=posix_identity(os.fstat(pfd))')
text = text.replace(' if r55.r45._identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:os.close(pfd);raise ValueError("r57_parent_identity_changed")', ' if posix_identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:os.close(pfd);raise ValueError("r57_parent_identity_changed")')
text = text.replace('   dfd=os.open(stage,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0));os.fsync(dfd);os.close(dfd)\n   sfd=os.open(stage.name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd)', '   fsync_dir(stage)\n   sfd=open_at(pfd, stage.name)')
text = text.replace('   if r55.r45._identity(os.fstat(pfd))!=parent_id or r55.r45._identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:raise ValueError("r57_parent_identity_changed")\n   r55.r45._rename_noreplace_at(pfd,stage.name,out.name);stage=None;published=True\n   tfd=os.open(out.name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd);target_id=r55.r45._identity(os.fstat(tfd))', '   if posix_identity(os.fstat(pfd))!=parent_id or posix_identity(os.stat(out.parent,follow_symlinks=False))!=parent_id:raise ValueError("r57_parent_identity_changed")\n   rename_noreplace_at(pfd,stage.name,out.name);stage=None;published=True\n   tfd=open_at(pfd, out.name);target_id=posix_identity(os.fstat(tfd))')
text = text.replace('    try:os.fsync(pfd)\n    except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"],parent_id,target_id) from exc\n    check=os.open(out.name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd)', '    try:fsync_dir(pfd)\n    except OSError as exc:raise PublicationDurabilityError(out,manifest["package_set_sha256"],parent_id,target_id) from exc\n    check=open_at(pfd, out.name)')
text = text.replace('     if r55.r45._identity(os.fstat(check))!=target_id or r55.r45._identity(os.fstat(tfd))!=target_id or r55.r45._identity(os.stat(out.parent,follow_symlinks=False))!=parent_id or _capture_dirfd(tfd)!=files or _capture_dirfd(check)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,target_id)', '     if posix_identity(os.fstat(check))!=target_id or posix_identity(os.fstat(tfd))!=target_id or posix_identity(os.stat(out.parent,follow_symlinks=False))!=parent_id or _capture_dirfd(tfd)!=files or _capture_dirfd(check)!=files:raise PublicationIntegrityError(out,manifest["package_set_sha256"],parent_id,target_id)')

# verify
text = text.replace(' manifest,expected=_build(*args,**kwargs);before=r55.r45._identity(os.stat(directory,follow_symlinks=False));dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))', ' manifest,expected=_build(*args,**kwargs);before=posix_identity(os.stat(directory,follow_symlinks=False));dfd=open_dir(directory)')
text = text.replace('   if r55.r45._identity(os.fstat(dfd))!=before or _capture_dirfd(dfd)!=expected or r55.r45._identity(os.stat(directory,follow_symlinks=False))!=before:raise ValueError("r57_package_or_context_mismatch")', '   if posix_identity(os.fstat(dfd))!=before or _capture_dirfd(dfd)!=expected or posix_identity(os.stat(directory,follow_symlinks=False))!=before:raise ValueError("r57_package_or_context_mismatch")')

# reconcile
text = text.replace(' manifest,expected=_build(*args,**kwargs);pfd=os.open(error.parent_path,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0))', ' manifest,expected=_build(*args,**kwargs);pfd=open_dir(error.parent_path)')
text = text.replace('   if r55.r45._identity(os.fstat(pfd))!=error.parent_identity or r55.r45._identity(os.stat(error.parent_path,follow_symlinks=False))!=error.parent_identity:raise ValueError("r57_reconcile_parent_identity_mismatch")\n   tfd=os.open(error.target_name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd)', '   if posix_identity(os.fstat(pfd))!=error.parent_identity or posix_identity(os.stat(error.parent_path,follow_symlinks=False))!=error.parent_identity:raise ValueError("r57_reconcile_parent_identity_mismatch")\n   tfd=open_at(pfd, error.target_name)')
text = text.replace('    if r55.r45._identity(os.fstat(tfd))!=error.target_identity or _capture_dirfd(tfd)!=expected:raise ValueError("r57_reconcile_target_identity_mismatch")\n    os.fsync(pfd);check=os.open(error.target_name,os.O_RDONLY|os.O_DIRECTORY|getattr(os,"O_NOFOLLOW",0),dir_fd=pfd)', '    if posix_identity(os.fstat(tfd))!=error.target_identity or _capture_dirfd(tfd)!=expected:raise ValueError("r57_reconcile_target_identity_mismatch")\n    fsync_dir(pfd);check=open_at(pfd, error.target_name)')
text = text.replace('     if r55.r45._identity(os.fstat(check))!=error.target_identity or _capture_dirfd(tfd)!=expected or _capture_dirfd(check)!=expected or r55.r45._identity(os.stat(error.output,follow_symlinks=False))!=error.target_identity:raise ValueError("r57_reconcile_identity_changed")', '     if posix_identity(os.fstat(check))!=error.target_identity or _capture_dirfd(tfd)!=expected or _capture_dirfd(check)!=expected or posix_identity(os.stat(error.output,follow_symlinks=False))!=error.target_identity:raise ValueError("r57_reconcile_identity_changed")')

p.write_text(text, encoding='utf-8')
print('fixed r57')
import py_compile
py_compile.compile(str(p), doraise=True)
print('compile ok')
