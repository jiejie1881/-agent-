"""Python-only synthetic collection protocol. NOT native Chroma/persistence acceptance."""
from copy import deepcopy
import math
from pathlib import Path


def install(workspace):
    from app.rag.vector_store import ChromaVectorStore
    from app.rag.exceptions import KnowledgeBaseNotReadyError
    collections = {}

    class Collection:
        def __init__(self):
            self.rows = {}

        def add(self, ids, documents, embeddings, metadatas):
            assert not (set(ids) & set(self.rows)) and len(set(ids)) == len(ids)
            for key, doc, vector, meta in zip(ids, documents, embeddings, metadatas):
                self.rows[key] = (doc, list(vector), deepcopy(meta))

        def count(self):
            return len(self.rows)

        def update(self, ids, embeddings=None, documents=None, metadatas=None):
            for i,key in enumerate(ids):
                old=self.rows[key]
                self.rows[key]=(documents[i] if documents is not None else old[0],
                    list(embeddings[i]) if embeddings is not None else old[1],
                    deepcopy(metadatas[i]) if metadatas is not None else old[2])

        def delete(self, ids):
            for key in ids:
                self.rows.pop(key,None)

        def get(self, include=None, ids=None, **kwargs):
            keys = [k for k in self.rows if ids is None or k in ids]
            return {'ids': keys, 'documents': [self.rows[k][0] for k in keys],
                    'embeddings': [list(self.rows[k][1]) for k in keys],
                    'metadatas': [deepcopy(self.rows[k][2]) for k in keys]}

        def query(self, query_embeddings, n_results, where=None, ids=None, include=None):
            vector = query_embeddings[0]
            def distance(other):
                if len(other) != len(vector):
                    raise ValueError('Synthetic vector dimension mismatch')
                norm = math.sqrt(sum(v*v for v in vector) * sum(v*v for v in other))
                return 1 - sum(a*b for a,b in zip(vector, other))/norm if norm else 1.0
            pairs = sorted([(distance(row[1]), key) for key,row in self.rows.items()
                if (ids is None or key in ids) and (where is None or all(row[2].get(k)==v for k,v in where.items()))])[:n_results]
            data = self.get(ids=[key for _,key in pairs])
            by_id = {key:i for i,key in enumerate(data['ids'])}
            keys = [key for _,key in pairs]
            return {'ids':[keys], 'documents':[[data['documents'][by_id[k]] for k in keys]],
                    'metadatas':[[data['metadatas'][by_id[k]] for k in keys]], 'distances':[[d for d,_ in pairs]]}

    class Client:
        def __init__(self, path):
            self.path = str(path)

        def get_or_create_collection(self, name, metadata=None):
            return collections.setdefault((self.path,name), Collection())

        def get_collection(self, name):
            if (self.path,name) not in collections:
                raise KnowledgeBaseNotReadyError('Synthetic collection not built')
            return collections[(self.path,name)]

    def client(store, *, create_directory):
        path = Path(store.persist_directory).resolve()
        if not path.is_relative_to(workspace.resolve()):
            raise PermissionError('Synthetic collection must be in the current test root')
        if create_directory:
            path.mkdir(parents=True, exist_ok=True)
        return Client(path)
    ChromaVectorStore._client = client
