"""Read image evidence without executing the image or extracting untrusted paths."""
import posixpath
import tarfile
import weakref


class Rootfs:
    def __init__(self, path):
        self.archive = tarfile.open(path)
        self._close = weakref.finalize(self, self.archive.close)
        self.members = {m.name.removeprefix('./').lstrip('/'): m for m in self.archive}

    def read(self, path, seen=None):
        name = posixpath.normpath(path.removeprefix('./').lstrip('/'))
        if name.startswith('../') or name == '..':
            raise ValueError('Path escapes image')
        member = self.members.get(name)
        if not member:
            return ''
        seen = set() if seen is None else seen
        if name in seen:
            raise ValueError('Cyclic image link')
        seen.add(name)
        if member.issym() or member.islnk():
            target = member.linkname
            if not target.startswith('/') and member.issym():
                target = posixpath.join(posixpath.dirname(name), target)
            return self.read(target, seen)
        if not member.isfile():
            return ''
        if member.size > 128 * 1024 * 1024:
            raise ValueError('Evidence file exceeds 128 MiB: ' + name)
        return self.archive.extractfile(member).read().decode('utf-8', errors='replace')

    def licenses_near(self, location):
        """Package-local notices only; never assign a sibling package's license."""
        location = location.lstrip('/')
        directory = posixpath.dirname(location)
        candidates = []
        for name in self.members:
            if name.startswith(directory + '/') and '/node_modules/' not in name[len(directory) + 1:]:
                leaf = posixpath.basename(name).lower()
                if leaf.startswith(('license', 'licence', 'copying', 'copyright', 'notice')):
                    text = self.read(name)
                    if text.strip():
                        candidates.append((name, text))
        return candidates
