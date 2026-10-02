"""Construct neutral learner files using explicit file and field boundaries."""
import io, os, re, struct, zipfile, zlib
from pathlib import Path, PureWindowsPath
from PIL import Image
import pipeline_core as v

NEUTRAL_TIME = 315532800

def neutral_filesystem(path):
    """Set stable delivery timestamps without probing account or OS attributes."""
    path=Path(path)
    if path.is_symlink():raise ValueError('Symlink in delivery')
    os.utime(path,(NEUTRAL_TIME,NEUTRAL_TIME))

def png_chunks(data):
    if not data.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Not a PNG')
    offset = 8
    while offset < len(data):
        size = struct.unpack('>I', data[offset:offset+4])[0]
        end = offset + size + 12
        if end > len(data): raise ValueError('Truncated PNG')
        kind = data[offset+4:offset+8]; payload = data[offset+8:end-4]
        if zlib.crc32(kind+payload) & 0xffffffff != struct.unpack('>I', data[end-4:end])[0]:
            raise ValueError('Invalid PNG checksum')
        yield kind, payload, data[offset:end]
        offset = end
        if kind == b'IEND':
            if offset != len(data): raise ValueError('Trailing PNG payload')
            return
    raise ValueError('Missing PNG end')

PNG_ALLOWED = {b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'sRGB', b'gAMA', b'cHRM', b'pHYs'}

def clean_png(data):
    # Crop PNGs are RGB, without ICC colour transforms. Reject unsupported colour
    # profiles rather than silently changing their appearance.
    chunks = list(png_chunks(data))
    if any(k == b'iCCP' for k, _, _ in chunks): raise ValueError('ICC PNG needs explicit colour review')
    result = b'\x89PNG\r\n\x1a\n' + b''.join(raw for k, _, raw in chunks if k in PNG_ALLOWED)
    a, b = Image.open(io.BytesIO(data)), Image.open(io.BytesIO(result))
    assert a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()
    return result

def sanitize_pdf(source, destination, title):
    """Reuse original vector pages and highlights, remove non-teaching metadata.

    Full nonincremental save removes unreachable old objects. Do not scrub hidden
    text or clean content streams: that could damage the source page itself.
    """
    with v.fitz.open(source) as doc:
        doc.scrub(attached_files=True, clean_pages=False, embedded_files=True,
                  hidden_text=False, javascript=True, metadata=True, redactions=False,
                  remove_links=True, reset_fields=True, reset_responses=True,
                  thumbnails=True, xml_metadata=True)
        for n in range(1, doc.xref_length()):
            for key in ('Metadata','PieceInfo','LastModified'):
                if doc.xref_get_key(n,key)[0] != 'null': doc.xref_set_key(n,key,'null')
        for page in doc:
            for annot in page.annots() or []:
                # The exact reviewed highlight geometry and appearance remain.
                for key in ('T','Contents','Subj','CreationDate','M','NM','RC','IRT','Popup'):
                    if doc.xref_get_key(annot.xref,key)[0] != 'null': doc.xref_set_key(annot.xref,key,'null')
        doc.set_toc([[1, f'Source page {n+1}', n+1] for n in range(len(doc))])
        doc.set_metadata({'title': title, 'author':'', 'subject':'', 'keywords':'',
                          'creator':'', 'producer':'', 'creationDate':'', 'modDate':''})
        doc.xref_set_key(-1, 'ID', 'null')
        doc.save(destination, garbage=4, deflate=True, no_new_id=True)
    neutral_filesystem(destination)


def check_files(folder,allowed):
    """Cheap structural boundary, not a content/privacy audit."""
    folder=Path(folder)
    if folder.is_symlink() or folder.is_junction() or not folder.is_dir():raise ValueError('Invalid delivery folder')
    if len(allowed)!=len({name.casefold() for name in allowed}):raise ValueError('Duplicate or case-colliding delivery name')
    for name in allowed:
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*',name)
                or name.endswith('.') or PureWindowsPath(name).is_reserved()):
            raise ValueError('Delivery names must be portable relative file names')
    if {p.name for p in folder.iterdir()}!=set(allowed):raise ValueError('Unexpected/missing learner file')
    if any((folder/n).is_symlink() or not (folder/n).is_file() for n in allowed):
        raise ValueError('Delivery requires regular files')
    return {n:v.digest(folder/n) for n in allowed}

def publish_bytes(stage,target,allowed):
    """Copy only selected bytes; preserve existing versions."""
    if target.exists() or (target.parent.exists() and any(p.name.casefold()==target.name.casefold() for p in target.parent.iterdir())):
        raise FileExistsError('Versioned delivery already exists (case-insensitive comparison)')
    expected=check_files(stage,allowed)
    target.mkdir(parents=True,exist_ok=False)
    for name in allowed:
        path=target/name
        path.write_bytes((stage/name).read_bytes())
        neutral_filesystem(path)
    neutral_filesystem(target)
    if check_files(target,allowed)!=expected:raise ValueError('Published bytes differ from accepted build')
    return {'status':'pass','files':len(allowed),'exact_bytes':True}

def archive_bytes(folder,destination,allowed):
    expected=check_files(folder,allowed)
    if destination.exists():raise FileExistsError('Sharing archive version already exists')
    with zipfile.ZipFile(destination,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in allowed:
            info=zipfile.ZipInfo(folder.name+'/'+name,date_time=(1980,1,1,0,0,0))
            info.create_system=0;info.external_attr=0o100644<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,(folder/name).read_bytes())
    with zipfile.ZipFile(destination) as archive:
        if set(archive.namelist())!={folder.name+'/'+n for n in allowed}:raise ValueError('Archive member mismatch')
        for name in allowed:
            import hashlib
            if hashlib.sha256(archive.read(folder.name+'/'+name)).hexdigest()!=expected[name]:
                raise ValueError('Archive payload mismatch')
    return {'status':'pass','members':len(allowed),'archive_sha256':v.digest(destination),'exact_bytes':True}
