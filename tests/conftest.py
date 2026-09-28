import os
from pathlib import Path
data_dir = Path(__file__).resolve().parents[1] / 'data'
p = data_dir / 'test_platform.db'
for x in [p, Path(str(p)+'-wal'), Path(str(p)+'-shm')]:
    if x.exists(): x.unlink()
os.environ['VISION_KNOWLEDGE_DB']=f'sqlite:///{p}'
os.environ['VISION_KNOWLEDGE_DATA'] = str(data_dir / 'test_data')
