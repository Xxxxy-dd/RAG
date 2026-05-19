from pathlib import Path
import sys
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

from rag.workers.vector_worker import VectorWorker

w = VectorWorker()
try:
    vs = w._load_vector_store()
    print('vector_store:', type(vs))
    # try a dry run add
    from langchain_core.documents import Document
    d = Document(page_content='hello world', metadata={'source':'test'})
    try:
        vs.add_documents(documents=[d], ids=['test-1'])
        print('add_documents OK')
    except Exception as e:
        print('add_documents failed:', e)
except Exception as e:
    print('load_vector_store failed:', e)
