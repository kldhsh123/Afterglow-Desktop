"""Run the installed original importer in an isolated, managed child process."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys


async def run():
    component = Path(sys.argv[1]).resolve()
    sys.path[:0] = [str(component / 'app'), str(component / 'deps')]
    handles = [os.add_dll_directory(str(path)) for path in (component / 'deps').glob('*.libs')] if os.name == 'nt' else []
    from xuwen.config import get_settings
    from xuwen.ingestion.image_importer import import_history_images
    from xuwen.ingestion.cli import _auto_build_vector_indices
    settings = get_settings()
    result = await import_history_images(Path(sys.argv[2]), settings)
    await _auto_build_vector_indices(settings, 'en' if os.environ.get('XUWEN_LANGUAGE') == 'en' else 'zh-CN')
    return asdict(result)


if __name__ == '__main__':
    try:
        output = {'ok': True, 'report': asyncio.run(run())}
    except Exception as error:
        output = {'ok': False, 'error': type(error).__name__ + ': ' + str(error)}
    print('AFTERGLOW_IMAGE_RESULT:' + json.dumps(output, ensure_ascii=False), flush=True)
    sys.exit(0 if output['ok'] else 1)
