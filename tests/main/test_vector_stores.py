from types import SimpleNamespace
from typing import List

import pytest
from dotenv import load_dotenv

from langroid.embedding_models.models import OpenAIEmbeddingsConfig
from langroid.mytypes import DocMetaData, Document
from langroid.parsing.parser import Parser, ParsingConfig, Splitter
from langroid.utils.system import rmdir
from langroid.vector_store.base import VectorStore
from langroid.vector_store.chromadb import ChromaDB, ChromaDBConfig
from langroid.vector_store.lancedb import LanceDB, LanceDBConfig
from langroid.vector_store.meilisearch import MeiliSearch, MeiliSearchConfig
from langroid.vector_store.momento import MomentoVI, MomentoVIConfig
from langroid.vector_store.qdrantdb import QdrantDB, QdrantDBConfig

load_dotenv()
embed_cfg = OpenAIEmbeddingsConfig(
    model_type="openai",
)

phrases = SimpleNamespace(
    HELLO="hello",
    HI_THERE="hi there",
    CANADA="people living in Canada",
    NOT_CANADA="people not living in Canada",
    OVER_40="people over 40",
    UNDER_40="people under 40",
    FRANCE="what is the capital of France?",
    BELGIUM="which city is Belgium's capital?",
)


class MyDocMetaData(DocMetaData):
    id: str


class MyDoc(Document):
    content: str
    metadata: MyDocMetaData


stored_docs = [
    MyDoc(content=d, metadata=MyDocMetaData(id=str(i)))
    for i, d in enumerate(vars(phrases).values())
]


@pytest.fixture(scope="function")
def vecdb(request) -> VectorStore:
    if request.param == "qdrant_local":
        qd_dir = ":memory:"
        qd_cfg = QdrantDBConfig(
            cloud=False,
            collection_name="test-" + embed_cfg.model_type,
            storage_path=qd_dir,
            embedding=embed_cfg,
        )
        qd = QdrantDB(qd_cfg)
        qd.add_documents(stored_docs)
        yield qd
        return

    if request.param == "qdrant_cloud":
        qd_dir = ".qdrant/cloud/" + embed_cfg.model_type
        qd_cfg_cloud = QdrantDBConfig(
            cloud=True,
            collection_name="test-" + embed_cfg.model_type,
            storage_path=qd_dir,
            embedding=embed_cfg,
        )
        qd_cloud = QdrantDB(qd_cfg_cloud)
        qd_cloud.add_documents(stored_docs)
        yield qd_cloud
        qd_cloud.delete_collection(collection_name=qd_cfg_cloud.collection_name)
        return

    if request.param == "chroma":
        cd_dir = ".chroma/" + embed_cfg.model_type
        rmdir(cd_dir)
        cd_cfg = ChromaDBConfig(
            collection_name="test-" + embed_cfg.model_type,
            storage_path=cd_dir,
            embedding=embed_cfg,
        )
        cd = ChromaDB(cd_cfg)
        cd.add_documents(stored_docs)
        yield cd
        rmdir(cd_dir)
        return

    if request.param == "meilisearch":
        ms_cfg = MeiliSearchConfig(
            collection_name="test-meilisearch",
        )
        ms = MeiliSearch(ms_cfg)
        ms.add_documents(stored_docs)
        yield ms
        ms.delete_collection(collection_name=ms_cfg.collection_name)
        return

    if request.param == "momento":
        cfg = MomentoVIConfig(
            collection_name="test-momento",
        )
        vdb = MomentoVI(cfg)
        vdb.add_documents(stored_docs)
        yield vdb
        vdb.delete_collection(collection_name=cfg.collection_name)

    if request.param == "lancedb":
        ldb_dir = ".lancedb/data/" + embed_cfg.model_type
        rmdir(ldb_dir)
        ldb_cfg = LanceDBConfig(
            cloud=False,
            collection_name="test-" + embed_cfg.model_type,
            storage_path=ldb_dir,
            embedding=embed_cfg,
            document_class=MyDoc,  # IMPORTANT, to ensure table has full schema!
        )
        ldb = LanceDB(ldb_cfg)
        ldb.add_documents(stored_docs)
        yield ldb
        rmdir(ldb_dir)
        return


@pytest.mark.parametrize(
    "query,results,exceptions",
    [
        ("which city is Belgium's capital?", [phrases.BELGIUM], ["meliseach"]),
        ("capital of France", [phrases.FRANCE], ["meliseach"]),
        ("hello", [phrases.HELLO], ["meliseach"]),
        ("hi there", [phrases.HI_THERE], ["meliseach"]),
        ("men and women over 40", [phrases.OVER_40], ["meilisearch"]),
        ("people aged less than 40", [phrases.UNDER_40], ["meilisearch"]),
        ("Canadian residents", [phrases.CANADA], ["meilisearch"]),
        ("people outside Canada", [phrases.NOT_CANADA], ["meilisearch"]),
    ],
)
# add "momento" when their API docs are ready
@pytest.mark.parametrize(
    "vecdb",
    ["lancedb", "qdrant_cloud", "qdrant_local", "chroma"],
    indirect=True,
)
def test_vector_stores_search(
    vecdb, query: str, results: List[str], exceptions: List[str]
):
    if vecdb.__class__.__name__.lower() in exceptions:
        # we don't expect some of these to work,
        # e.g. MeiliSearch is a text search engine, not a vector store
        return
    docs_and_scores = vecdb.similar_texts_with_scores(query, k=len(vars(phrases)))
    # first doc should be best match
    # scores are cosine similarities, so high means close
    matching_docs = [doc.content for doc, score in docs_and_scores if score > 0.7]
    assert set(results).issubset(set(matching_docs))


# add "momento" when their API docs are ready.
@pytest.mark.parametrize(
    "vecdb",
    ["lancedb", "qdrant_local", "qdrant_cloud", "chroma"],
    indirect=True,
)
def test_vector_stores_access(vecdb):
    assert vecdb is not None

    coll_name = vecdb.config.collection_name
    assert coll_name is not None

    vecdb.delete_collection(collection_name=coll_name)
    vecdb.create_collection(collection_name=coll_name)

    vecdb.add_documents(stored_docs)
    all_docs = vecdb.get_all_documents()
    ids = [doc.id() for doc in all_docs]
    assert len(all_docs) == len(stored_docs)

    docs = vecdb.get_documents_by_ids(ids[:3])
    assert len(docs) == 3

    coll_names = [f"test_junk_{i}" for i in range(3)]
    for coll in coll_names:
        vecdb.create_collection(collection_name=coll)
    n_colls = len(
        [c for c in vecdb.list_collections(empty=True) if c.startswith("test_junk")]
    )
    n_dels = vecdb.clear_all_collections(really=True, prefix="test_junk")
    assert n_colls == n_dels


@pytest.mark.parametrize(
    "vecdb",
    ["qdrant_cloud", "lancedb", "chroma", "qdrant_local"],
    indirect=True,
)
def test_vector_stores_context_window(vecdb):
    """Test whether retrieving context-window around matches is working."""

    phrases = SimpleNamespace(
        CATS="Cats are quiet and clean.",
        DOGS="Dogs are noisy and messy.",
        GIRAFFES="Giraffes are tall and quiet.",
        ELEPHANTS="Elephants are big and noisy.",
        OWLS="Owls are quiet and nocturnal.",
        BATS="Bats are nocturnal and noisy.",
    )
    text = "\n\n".join(vars(phrases).values())
    doc = Document(content=text, metadata=DocMetaData(id="0"))

    cfg = ParsingConfig(
        splitter=Splitter.SIMPLE,
        n_neighbor_ids=2,
        chunk_size=1,
        max_chunks=20,
        min_chunk_chars=3,
        discard_chunk_chars=1,
    )

    parser = Parser(cfg)
    splits = parser.split([doc])

    vecdb.create_collection(collection_name="test-context-window", replace=True)
    vecdb.add_documents(splits)

    # Test context window retrieval
    docs_scores = vecdb.similar_texts_with_scores("What are Giraffes like?", k=1)
    docs_scores = vecdb.add_context_window(docs_scores, neighbors=2)

    assert len(docs_scores) == 1
    giraffes, score = docs_scores[0]
    assert all(
        p in giraffes.content
        for p in [
            phrases.CATS,
            phrases.DOGS,
            phrases.GIRAFFES,
            phrases.ELEPHANTS,
            phrases.OWLS,
        ]
    )
    # check they are in the right sequence
    indices = [
        giraffes.content.index(p)
        for p in ["Cats", "Dogs", "Giraffes", "Elephants", "Owls"]
    ]
    assert indices == sorted(indices)


@pytest.mark.parametrize(
    "vecdb",
    ["lancedb", "chroma", "qdrant_cloud", "qdrant_local"],
    indirect=True,
)
def test_vector_stores_overlapping_matches(vecdb):
    """Test that overlapping windows are handled correctly."""

    # The windows around the first two giraffe matches should overlap.
    # The third giraffe match should be in a separate window.
    phrases = SimpleNamespace(
        CATS="Cats are quiet and clean.",
        DOGS="Dogs are noisy and messy.",
        GIRAFFES="Giraffes are tall and quiet.",
        ELEPHANTS="Elephants are big and noisy.",
        OWLS="Owls are quiet and nocturnal.",
        GIRAFFES1="Giraffes eat a lot of leaves.",
        COWS="Cows are quiet and gentle.",
        BULLS="Bulls are noisy and aggressive.",
        TIGERS="Tigers are big and noisy.",
        LIONS="Lions are nocturnal and noisy.",
        CHICKENS="Chickens are quiet and gentle.",
        ROOSTERS="Roosters are noisy and aggressive.",
        GIRAFFES3="Giraffes are really strange animals.",
        MICE="Mice are puny and gentle.",
        RATS="Rats are noisy and destructive.",
    )
    text = "\n\n".join(vars(phrases).values())
    doc = Document(content=text, metadata=DocMetaData(id="0"))

    cfg = ParsingConfig(
        splitter=Splitter.SIMPLE,
        n_neighbor_ids=2,
        chunk_size=1,
        max_chunks=20,
        min_chunk_chars=3,
        discard_chunk_chars=1,
    )

    parser = Parser(cfg)
    splits = parser.split([doc])

    vecdb.create_collection(collection_name="test-context-window", replace=True)
    vecdb.add_documents(splits)

    # Test context window retrieval
    docs_scores = vecdb.similar_texts_with_scores("What are Giraffes like?", k=3)
    # We expect to retrieve a window of -2, +2 around each of the three Giraffe matches.
    # The first two windows will overlap, so they form a connected component,
    # and we topological-sort and order the chunks in these windows, resulting in a
    # single window. The third Giraffe-match context window will not overlap with
    # the other two, so we will have a total of 2 final docs_scores components.
    docs_scores = vecdb.add_context_window(docs_scores, neighbors=2)

    assert len(docs_scores) == 2
    # verify no overlap in d.metadata.window_ids for d in docs
    all_window_ids = [id for d, _ in docs_scores for id in d.metadata.window_ids]
    assert len(all_window_ids) == len(set(all_window_ids))

    # verify giraffe occurs in each /match
    assert all("Giraffes" in d.content for d, _ in docs_scores)

    # verify correct sequence of chunks in each match
    sentences = vars(phrases).values()
    for d, _ in docs_scores:
        content = d.content
        indices = [content.find(p) for p in sentences]
        indices = [i for i in indices if i >= 0]
        assert indices == sorted(indices)
