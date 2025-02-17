import pytest

from langroid.mytypes import Document
from langroid.parsing.parser import Parser, ParsingConfig, Splitter
from langroid.parsing.utils import generate_random_text

CHUNK_SIZE = 100


@pytest.mark.parametrize(
    "splitter, chunk_size, max_chunks, min_chunk_chars, discard_chunk_chars",
    [
        # (Splitter.TOKENS, 10, 100, 35, 2),
        (Splitter.PARA_SENTENCE, 10, 3000, 35, 2),
        (Splitter.SIMPLE, 10, 500 * 5, 35, 2),
    ],
)
def test_parser(
    splitter: Splitter,
    chunk_size: int,
    max_chunks: int,
    min_chunk_chars: int,
    discard_chunk_chars: int,
):
    cfg = ParsingConfig(
        splitter=splitter,
        n_neighbor_ids=2,
        chunk_size=chunk_size,
        max_chunks=max_chunks,
        separators=["."],
        min_chunk_chars=min_chunk_chars,
        discard_chunk_chars=discard_chunk_chars,
        token_encoding_model="text-embedding-ada-002",
    )

    parser = Parser(cfg)
    docs = [
        Document(content=generate_random_text(500), metadata={"id": i})
        for i in range(5)
    ]

    split_docs = parser.split(docs)

    assert all(parser.num_tokens(d.content) <= chunk_size + 5 for d in split_docs)
    assert len(split_docs) <= max_chunks * len(docs)
    assert all(len(d.content) >= discard_chunk_chars for d in split_docs)
    assert all(d.metadata.is_chunk for d in split_docs)

    # test neighbor chunks
    doc = Document(content=generate_random_text(500), metadata={"id": 0})
    chunks = parser.split([doc])
    n = len(chunks)
    if n > 2 * cfg.n_neighbor_ids + 1:
        assert len(chunks[n // 2].metadata.window_ids) == 2 * cfg.n_neighbor_ids + 1


def length_fn(text):
    return len(text.split())  # num chars


@pytest.mark.parametrize(
    "chunk_size, max_chunks, min_chunk_chars, discard_chunk_chars",
    [
        (100, 10_000, 350, 5),
        (10, 100, 35, 2),
        (200, 1000, 300, 10),
    ],
)
def test_text_token_chunking(
    chunk_size: int, max_chunks: int, min_chunk_chars: int, discard_chunk_chars: int
):
    cfg = ParsingConfig(
        chunk_size=chunk_size,
        max_chunks=max_chunks,
        min_chunk_chars=min_chunk_chars,
        discard_chunk_chars=discard_chunk_chars,
        token_encoding_model="text-embedding-ada-002",
    )

    parser = Parser(cfg)

    text = generate_random_text(60)
    chunks = parser.chunk_tokens(text)

    assert len(chunks) <= max_chunks
    assert all(len(c) >= discard_chunk_chars for c in chunks)
    assert all(parser.num_tokens(c) <= chunk_size + 5 for c in chunks)
