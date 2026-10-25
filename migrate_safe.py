import pathlib, re

domain = pathlib.Path('ledger/domain')
targets = [
    'direct_trip_airfare_atomic_admission.py',
    'direct_trip_cancel_atomic_admission.py',
    'direct_mytrip_airfare_atomic_admission.py',
    'direct_trip_cancel_provenance.py',
    'direct_kbo_signature_cardinality.py',
    'direct_kb_confirmation_evidence.py',
    'direct_trip_cancel_lifecycle_evidence.py',
    'direct_agoda_customer_service_evidence.py',
    'direct_document_acquisition_census.py',
    'direct_external_manual_evidence.py',
    'direct_manual_group_taxonomy_evidence.py',
    'direct_merchant_taxonomy_support.py',
    'direct_narrow_service_classification.py',
    'direct_original_approval_relation.py',
    'direct_ota_lifecycle_support.py',
    'direct_receipt_airfare_evidence.py',
    'direct_receipt_airfare_provenance.py',
    'direct_repository_booking_evidence.py',
    'direct_verified_booking_evidence.py',
    'han_master_candidate.py',
]

def add_import(text):
    if 'posix_publication' in text:
        return text
    if 'from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT' in text:
        return text.replace(
            'from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT',
            'from ledger.domain.direct_lineage_annex import REPOSITORY_ROOT\nfrom ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity'
        )
    if 'from pathlib import Path' in text:
        return text.replace(
            'from pathlib import Path',
            'from pathlib import Path\nfrom ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity'
        )
    # fallback
    lines=text.splitlines()
    for i,l in enumerate(lines):
        if l.startswith('import ') or l.startswith('from '):
            last=i
    lines.insert(last+1, 'from ledger.domain.posix_publication import open_dir, open_nofollow, open_at, verify_regular_single_link, fsync_dir, rename_noreplace, rename_noreplace_at, identity as posix_identity')
    return '\n'.join(lines)

def parse_os_open_calls(text):
    # find all os.open( and extract balanced parens
    calls=[]
    idx=0
    while True:
        pos=text.find('os.open(', idx)
        if pos==-1:
            break
        depth=0
        end=pos
        # find opening paren at pos+7
        paren_start=text.find('(', pos)
        if paren_start==-1:
            break
        depth=0
        for i in range(paren_start, len(text)):
            if text[i]=='(':
                depth+=1
            elif text[i]==')':
                depth-=1
                if depth==0:
                    end=i
                    break
        if depth!=0:
            idx=end+1
            continue
        call=text[pos:end+1]
        calls.append((pos,end,call))
        idx=end+1
    return calls

def replace_os_open(text):
    # process from end to start to avoid offset issues
    calls=parse_os_open_calls(text)
    # sort reverse
    for pos,end,call in reversed(calls):
        # Determine if this call has dir_fd
        if 'O_CREAT' in call:
            continue # file creation, keep
        # Extract first arg
        # call is os.open(args)
        inner=call[len('os.open('):-1]
        # split args handling commas but not inside parens; for our cases first arg is simple path or name without commas
        # Find first comma not inside nested parens
        depth=0
        comma_pos=-1
        for i,ch in enumerate(inner):
            if ch=='(':
                depth+=1
            elif ch==')':
                depth-=1
            elif ch==',' and depth==0:
                comma_pos=i
                break
        if comma_pos==-1:
            continue
        first_arg=inner[:comma_pos].strip()
        rest=inner[comma_pos+1:].strip()
        has_dir_fd='dir_fd' in call
        has_O_DIRECTORY='O_DIRECTORY' in call
        has_O_NOFOLLOW='O_NOFOLLOW' in call
        if has_dir_fd:
            # extract dir_fd value
            m=re.search(r'dir_fd\s*=\s*([^,\)]+)', call)
            if m:
                dirfd=m.group(1).strip()
                # preserve possible trailing spaces
                replacement=f'open_at({dirfd}, {first_arg})'
                text=text[:pos]+replacement+text[end+1:]
        else:
            if has_O_DIRECTORY:
                # directory open without dir_fd -> open_dir
                replacement=f'open_dir({first_arg})'
                text=text[:pos]+replacement+text[end+1:]
            elif has_O_NOFOLLOW:
                replacement=f'open_nofollow({first_arg})'
                text=text[:pos]+replacement+text[end+1:]
            else:
                # no special flag, keep
                pass
    return text

def replace_flags_var(text):
    # for _secure_read where flags variable used
    # pattern: flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW"...); try:fd=os.open(path,flags)
    # We already handled explicit, but variable case remains: os.open(path,flags)
    # If text contains that flags definition, replace os.open(path,flags) with open_nofollow(path)
    if 'flags=os.O_RDONLY|getattr(os,"O_NOFOLLOW"' in text or 'flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW"' in text or "flags=os.O_RDONLY|getattr(os,\"O_NOFOLLOW\"" in text:
        # replace specific occurrences: os.open(path,flags) and os.open(path, flags)
        # Need to handle both path var names: path, path, etc.
        # Use regex for os.open(some_path,flags) where second arg is exactly flags
        text=re.sub(r'os\.open\(\s*([^,]+?)\s*,\s*flags\s*\)', r'open_nofollow(\1)', text)
    return text

def replace_verify(text):
    # Insert verify calls before if checks containing S_ISREG and st_nlink
    lines=text.splitlines()
    out=[]
    i=0
    while i<len(lines):
        line=lines[i]
        if 'stat.S_ISREG' in line and 'st_nlink' in line and 'verify_regular_single_link' not in line:
            # Check if this is path-based (info.st_nlink) -> skip
            if 'info.st_nlink' in line or 'st.st_nlink' in line and 'os.fstat' not in ''.join(out[-3:]):
                out.append(line)
                i+=1
                continue
            # need fd var: infer from preceding fstat
            # Look back for os.fstat(fd) or os.fstat(check) etc.
            fd_var='fd'
            # search back up to 5 lines for fstat
            for back in range(max(0,i-5), i):
                m=re.search(r'os\.fstat\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)', lines[back])
                if m:
                    fd_var=m.group(1)
            # also check if line itself contains 'before.st_mode' etc., stat_var is before, but fd is separate
            # need to map stat_var to fd? For now assume fd_var found is correct
            # Determine mode
            mode=None
            if '0o600' in line and '0o644' not in line and '0o400' not in line:
                mode='0o600'
            elif '0o400' in line:
                mode='0o400'
            # Build verify line
            indent=line[:len(line)-len(line.lstrip())]
            if mode:
                verify_line=f'{indent}verify_regular_single_link({fd_var}, mode={mode})'
            else:
                verify_line=f'{indent}verify_regular_single_link({fd_var})'
            # Now trim condition: keep only uid and mode set checks
            # Parse if condition
            m_if=re.search(r'if\s+(.*):', line)
            if m_if:
                cond=m_if.group(1)
                # split by ' or ' or ' and '
                # We need to keep parts not containing S_ISREG or st_nlink
                # Use regex split preserving
                parts=re.split(r'\s+or\s+|\s+and\s+', cond)
                keep=[]
                for p in parts:
                    if 'S_ISREG' in p or 'st_nlink' in p:
                        continue
                    keep.append(p.strip())
                if keep:
                    # reconstruct with appropriate connector
                    # Determine original connector by checking cond
                    if ' or ' in cond:
                        new_cond=' or '.join(keep)
                    elif ' and ' in cond:
                        new_cond=' and '.join(keep)
                    else:
                        new_cond=' or '.join(keep)
                    m_raise=re.search(r'raise ValueError\(.*\)', line)
                    if m_raise:
                        new_line=f'{indent}if {new_cond}:{m_raise.group(0)}'
                    else:
                        # fallback: keep original suffix after ':'
                        suffix=line.split(':',1)[1] if ':' in line else ''
                        new_line=f'{indent}if {new_cond}:{suffix}'
                    out.append(verify_line)
                    out.append(new_line)
                else:
                    out.append(verify_line)
            else:
                out.append(verify_line)
                out.append(line)
        else:
            out.append(line)
        i+=1
    return '\n'.join(out)

def replace_fsync(text):
    # Replace directory fsync patterns
    # 1. trio: fd = os.open(stage, O_DIRECTORY); os.fsync(fd); os.close(fd) -> fsync_dir(stage)
    # Use regex for that specific pattern
    text=re.sub(r'fd\s*=\s*open_dir\(\s*stage\s*\)\s*;\s*fsync_dir\(fd\)\s*;\s*os\.close\(fd\)', 'fsync_dir(stage)', text)
    text=re.sub(r'os\.open\(\s*stage\s*,\s*os\.O_RDONLY\s*\|\s*getattr\(os,\s*"O_DIRECTORY",\s*0\)[^\)]*\)\s*;\s*os\.fsync\([^\)]+\)\s*;\s*os\.close\([^\)]+\)', 'fsync_dir(stage)', text)
    # 2. parent fsync: os.fsync(pfd) where pfd is directory fd -> fsync_dir(pfd) or fsync_dir(parent_path)
    # For publication, replace os.fsync(pfd) with fsync_dir(pfd) but our fsync_dir now doesn't close, so it's safe
    # We'll replace os.fsync(pfd) with fsync_dir(pfd) when pfd is not file fd
    # Heuristic: if var name contains pfd, dfd, parent, dir, stage
    def repl_fsync(m):
        var=m.group(1)
        if var=='fd':
            return m.group(0) # keep file fd
        if any(k in var for k in ['pfd','dfd','parent','stage','dir','dfd']):
            return f'fsync_dir({var})'
        return m.group(0)
    text=re.sub(r'os\.fsync\(\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\)', repl_fsync, text)
    # Also handle os.fsync(directory) etc. – already covered
    # For stage fsync where we already have fsync_dir(stage), keep
    return text

def replace_rename(text):
    # Replace def _rename_noreplace_at with wrapper
    pat=re.compile(r'def _rename_noreplace_at\(.*?\).*?:\n(?:[ \t].*\n)*?(?=\n\S|\ndef |\nclass |\Z)', re.MULTILINE)
    # We'll search for def _rename_noreplace_at and replace its body
    # Simpler: find start and replace until next def or class or end
    # Use re.sub with function
    def repl_def(m):
        # limit to renameat2 block
        block=m.group(0)
        if 'renameat2' not in block:
            return block
        return 'def _rename_noreplace_at(parentfd, source, target):\n    from ledger.domain.posix_publication import rename_noreplace_at as _pub_rename_at\n    return _pub_rename_at(parentfd, source, target)\n'
    text=re.sub(r'def _rename_noreplace_at\(.*?\):\n(?:.*\n)*?raise OSError\(.*?"r\d+_renameat2"\)\n', repl_def, text)
    # Replace calls
    text=re.sub(r'r\d+\._rename_noreplace_at', 'rename_noreplace_at', text)
    text=re.sub(r'r55\.r45\._rename_noreplace_at', 'rename_noreplace_at', text)
    text=re.sub(r'r45\._rename_noreplace_at', 'rename_noreplace_at', text)
    text=re.sub(r'r44\._rename_noreplace_at', 'rename_noreplace_at', text)
    return text

def replace_identity(text):
    # Remove lambda identity definitions and replace ident with posix_identity
    # Remove lines like 'ident=lambda x:(x.st_dev...' or 'identity=lambda x:...'
    text=re.sub(r'[ \t]*ident\s*=\s*lambda x:\(x\.st_dev.*\)\n', '', text)
    text=re.sub(r'[ \t]*identity\s*=\s*lambda x:\(x\.st_dev.*\)\n', '', text)
    # Replace ident( and identity( where they are local lambda usages (but not posix_identity)
    # We need to avoid replacing posix_identity
    # Use word boundary
    text=re.sub(r'\bident\(', 'posix_identity(', text)
    # For cases where they had 'identity(lambda' already, but we removed
    # Also replace r45._identity etc. with posix_identity where appropriate? Keep for now but also add import
    # For build functions they use r55.r45._identity etc. – we can also replace those with posix_identity for consistency
    # But to keep diff minimal, we'll keep rxx._identity as is; they will still work because posix_identity is more complete
    return text

for fname in targets:
    p=domain/fname
    if not p.exists():
        print(f'skip {fname}')
        continue
    text=p.read_text(encoding='utf-8')
    orig=text
    text=add_import(text)
    text=replace_os_open(text)
    text=replace_flags_var(text)
    text=replace_verify(text)
    text=replace_fsync(text)
    text=replace_rename(text)
    text=replace_identity(text)
    # Fix double parens from open_dir(stage)) etc. due to extra )
    text=text.replace('open_dir(stage))', 'open_dir(stage)')
    text=text.replace('open_dir(directory))', 'open_dir(directory)')
    text=text.replace('open_dir(error.parent_path))', 'open_dir(error.parent_path)')
    text=text.replace('open_dir(out.parent))', 'open_dir(out.parent)')
    text=text.replace('open_dir(parent))', 'open_dir(parent)')
    text=text.replace('open_dir(output.parent))', 'open_dir(output.parent)')
    # Fix open_at extra parens
    text=text.replace('open_at(pfd, stage.name))', 'open_at(pfd, stage.name)')
    # Clean up verify duplication where we inserted verify but original line still had uid check with stat.S_IMODE not in {…} -> keep
    if text!=orig:
        p.write_text(text, encoding='utf-8')
        print(f'migrated {fname}')
        try:
            import py_compile
            py_compile.compile(str(p), doraise=True)
            print('  compile ok')
        except Exception as e:
            print(f'  compile fail: {e}')
    else:
        print(f'no change {fname}')

# report remaining
for p in sorted(domain.glob('*.py')):
    t=p.read_text(encoding='utf-8')
    if p.name=='posix_publication.py':
        continue
    cnt=t.count('O_DIRECTORY')+t.count('O_NOFOLLOW')+t.count('renameat2')
    # also count st_nlink where not in verify? naive
    if cnt>0:
        print(f'remaining {p.name}: O_DIR={t.count("O_DIRECTORY")} O_NOF={t.count("O_NOFOLLOW")} rename={t.count("renameat2")}')
