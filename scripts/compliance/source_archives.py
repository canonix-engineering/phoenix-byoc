"""Download and inspect upstream archives without extracting or executing them."""
import hashlib
import io
import json
import re
import tarfile
import urllib.request
import zipfile
from pathlib import Path

MAX_DOWNLOAD = 512 * 1024 * 1024
NOTICE = re.compile(r'(?i)^(licen[cs]e|copying|copyright|notice|authors)(?:[._-].*)?$')


def fetch(url, cache):
    if not url.startswith('https://'):
        raise ValueError('Source download must use HTTPS: ' + url)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / hashlib.sha256(url.encode()).hexdigest()
    if path.exists():
        return path.read_bytes()
    request = urllib.request.Request(url, headers={'User-Agent': 'Phoenix-OSS-compliance/1'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Source download exceeds limit: ' + url)
    path.write_bytes(data)
    return data


def notices(data, origin):
    """Retain all license/notice files, including notices for bundled subprojects."""
    result = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for member in archive:
                if member.isfile() and member.size <= 4 * 1024 * 1024 and NOTICE.match(Path(member.name).name):
                    result.append({'origin': origin + '#' + member.name,
                                   'text': archive.extractfile(member).read().decode('utf-8', 'replace')})
    except tarfile.ReadError:
        if zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if member.file_size <= 4 * 1024 * 1024 and NOTICE.match(Path(member.filename).name):
                        result.append({'origin': origin + '#' + member.filename,
                                       'text': archive.read(member).decode('utf-8', 'replace')})
    if not result:
        # Some distributions keep notices only in source headers (e.g. Alpine's
        # ca-certificates). Preserve the original comment blocks, never fabricate
        # a copyright holder from package metadata.
        try:
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    header = archive.extractfile(member).read(32768).decode('utf-8', 'replace')
                    blocks = re.findall(r'/\*.*?\*/|(?m:^(?:[ \t]*(?:\#|//)[^\n]*\n)+)', header, re.S)
                    for block in blocks:
                        if re.search(r'(?i)copyright|license|licence|permission is hereby', block):
                            result.append({'origin': origin + '#' + member.name, 'text': block})
        except tarfile.ReadError:
            pass
    return [item for item in result if item['text'].strip()]


def source_bundle(files, directory, key, source_url, instructions):
    directory.mkdir(parents=True, exist_ok=True)
    archive_path = directory / (key + '.tar.gz')
    with archive_path.open('wb') as raw:
        import gzip
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w') as archive:
                for name, data in sorted(files.items()):
                    if name.startswith('/') or '..' in Path(name).parts:
                        raise ValueError('Unsafe source filename: ' + name)
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o644
                    archive.addfile(member, io.BytesIO(data))
    build_path = directory / (key + '.build.txt')
    build_path.write_text(instructions)
    return dict(sourceUrl=source_url, reviewedBy='automated upstream checksum and version verification',
                modifications='Upstream distribution sources and distribution patches; no Canonix modifications.',
                archive=archive_path.name, archiveSha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                buildInstructions=build_path.name, buildInstructionsSha256=hashlib.sha256(build_path.read_bytes()).hexdigest())
