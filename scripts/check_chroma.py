from langchain_chroma import Chroma
from pathlib import Path
from rag.indexes.chroma_viewer import CHROMA_DIR, DEFAULT_COLLECTION

print('chroma dir', CHROMA_DIR)
client = Chroma(collection_name=DEFAULT_COLLECTION, persist_directory=str(CHROMA_DIR))
try:
    data = client.get(include=['documents','metadatas','ids'], limit=10)
    print('ids len', len(data.get('ids') or []))
    for i, idd in enumerate(data.get('ids') or []):
        print(i, idd)
except Exception as e:
    print('error', e)
