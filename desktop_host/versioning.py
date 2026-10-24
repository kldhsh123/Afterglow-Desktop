"""Desktop release metadata shared by the host, repository checks and packaging."""
import re


def desktop_version(metadata):
    if (not isinstance(metadata, dict)
            or not isinstance(metadata.get('baseVersion'), str)
            or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', metadata['baseVersion'])
            or any(int(value) > 65535 for value in metadata['baseVersion'].split('.'))
            or type(metadata.get('internalBuild')) is not int
            or not 1 <= metadata['internalBuild'] <= 65535
            or metadata.get('channel', 'internal') not in ('internal', 'stable')):
        raise ValueError('Invalid desktop version file')
    if metadata.get('channel') == 'stable':
        return metadata['baseVersion']
    return f"{metadata['baseVersion']}-internal.{metadata['internalBuild']}"
