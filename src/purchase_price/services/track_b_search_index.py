"""Substring side index for the Track B serving SQLite (serving schema v4).

The price search filters ``track_b_delivery_lines`` with ``LIKE '%needle%'`` on the item title,
model key, class key and supplier. A leading ``%`` cannot use a B-tree index, so each such query
read the whole 2.5 GB file. This module keeps a trigram FTS5 index over those four columns plus a
small ``(id, transaction_date)`` table, both built by the serving-index sync.

The index is only a pre-filter. A search first asks it for the ids of rows that *can* match (a
superset: every trigram of the needle is present), ordered like the original query, then runs the
original SQLAlchemy statement - with every original condition - restricted to those ids in small
batches until the original LIMIT is reached. The returned rows are therefore exactly what the old
full-scan query returned, while only a few hundred table rows are read.

Whenever the index cannot narrow the rows safely (an older file without it, an index that is
behind the table, a SQLite build without FTS5, a one-character needle in an OR), the original
full-scan statement runs unchanged.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from purchase_price.models import TrackBDeliveryLine

SEARCH_FTS_TABLE = "track_b_search_fts"
SEARCH_ROWS_TABLE = "track_b_search_rows"
SEARCH_VOCAB_TABLE = "track_b_search_vocab"
SEARCH_COLUMNS = ("product_title", "model_key", "class_key", "supplier")
SEARCH_TABLES = (SEARCH_FTS_TABLE, SEARCH_ROWS_TABLE, SEARCH_VOCAB_TABLE)
# Recorded in the serving-index pointer. The side index is optional: the R2 object keeps the
# serving schema tag so an app process that has not restarted yet still accepts the new file.
SEARCH_INDEX_VERSION = "track-b-search-trigram-v1"
# session.info key: which path each substring query took ("index" or "legacy"), for audits.
PATHS_KEY = "track_b_search_index_paths"

# Appended to every indexed value so a two-character needle at the very end of a value is still
# the start of one trigram ("…심장" -> "심장\x01"). Needles never contain it.
_END = "\x01"
# Ids per follow-up table query; below SQLite's historic 999 bound-parameter limit.
FETCH_BATCH = 500
_READY_KEY = "track_b_search_index_ready"
# A two-character needle is looked up in the trigram vocabulary by its raw characters, so it must
# already be in the tokenizer's folded form: lower-case ASCII, digits and Hangul syllables.
_FOLDED_SHORT_NEEDLE = re.compile(r"[0-9a-z가-힣]{2}")
_LIKE_WILDCARDS = re.compile(r"[%_]")


@dataclass(frozen=True)
class Contains:
    """``column LIKE '%needle%'`` (SQLite LIKE: ASCII case-insensitive)."""

    column: str
    needle: str


@dataclass(frozen=True)
class AnyOf:
    parts: tuple[Any, ...]


@dataclass(frozen=True)
class AllOf:
    parts: tuple[Any, ...]


def sqlite_search_support() -> tuple[str, bool]:
    """(SQLite version, whether it has FTS5 with the trigram tokenizer) for diagnostics."""

    import sqlite3

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(x, tokenize='trigram')")
        supported = True
    except sqlite3.Error:
        supported = False
    finally:
        connection.close()
    return sqlite3.sqlite_version, supported


# ── Build (serving-index sync) ──


def _sqlite_master_names(connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name IN (?, ?, ?)", SEARCH_TABLES
        ).fetchall()
    }


def ensure_search_index(connection) -> dict[str, int]:
    """Create the side index if missing and add every table row it does not hold yet.

    ``connection`` is a SQLAlchemy Connection inside a transaction (``engine.begin()``). Rows are
    never deleted and their searchable values never change after insert (a later conflicting
    payload only flips ``identity_conflict``), so new rows are exactly ``id > max(indexed id)``.
    Returns {"created": 0/1, "added": n, "indexed_rows": total}.
    """

    created = 0
    if _sqlite_master_names(connection) != set(SEARCH_TABLES):
        for name in (SEARCH_VOCAB_TABLE, SEARCH_FTS_TABLE, SEARCH_ROWS_TABLE):
            connection.exec_driver_sql(f"DROP TABLE IF EXISTS {name}")
        connection.exec_driver_sql(
            f"CREATE VIRTUAL TABLE {SEARCH_FTS_TABLE} USING fts5("
            + ", ".join(SEARCH_COLUMNS)
            # contentless + detail=column + no per-row sizes: only (trigram -> ids, column).
            + ", content='', detail=column, columnsize=0, tokenize='trigram')"
        )
        connection.exec_driver_sql(
            f"CREATE TABLE {SEARCH_ROWS_TABLE} (id INTEGER PRIMARY KEY, transaction_date DATE)"
        )
        connection.exec_driver_sql(
            f"CREATE VIRTUAL TABLE {SEARCH_VOCAB_TABLE} USING fts5vocab({SEARCH_FTS_TABLE}, col)"
        )
        created = 1

    last_id = int(
        connection.exec_driver_sql(f"SELECT coalesce(max(id), 0) FROM {SEARCH_ROWS_TABLE}").scalar()
        or 0
    )
    values = ", ".join(f"{column} || char(1)" for column in SEARCH_COLUMNS)
    connection.exec_driver_sql(
        f"INSERT INTO {SEARCH_FTS_TABLE}(rowid, {', '.join(SEARCH_COLUMNS)}) "
        f"SELECT id, {values} FROM track_b_delivery_lines WHERE id > ? ORDER BY id",
        (last_id,),
    )
    added = connection.exec_driver_sql(
        f"INSERT INTO {SEARCH_ROWS_TABLE}(id, transaction_date) "
        "SELECT id, transaction_date FROM track_b_delivery_lines WHERE id > ? ORDER BY id",
        (last_id,),
    ).rowcount
    if created:
        # One merged segment keeps every needle at one b-tree lookup per trigram. Daily
        # increments are small and left to FTS5's automerge, so the file does not grow by a
        # full index rewrite each sync.
        connection.exec_driver_sql(
            f"INSERT INTO {SEARCH_FTS_TABLE}({SEARCH_FTS_TABLE}) VALUES ('optimize')"
        )
    indexed = int(
        connection.exec_driver_sql(f"SELECT count(*) FROM {SEARCH_ROWS_TABLE}").scalar() or 0
    )
    return {"created": created, "added": max(int(added or 0), 0), "indexed_rows": indexed}


# ── Query ──


def _quote(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def search_index_ready(session: Session) -> bool:
    """True when this SQLite file has a usable side index that covers every table row."""

    cached = session.info.get(_READY_KEY)
    if cached is not None:
        return bool(cached)
    ready = False
    try:
        bind = session.get_bind()
        if bind.dialect.name == "sqlite":
            names = {
                str(name)
                for name in session.execute(
                    text("SELECT name FROM sqlite_master WHERE name IN (:a, :b, :c)"),
                    {"a": SEARCH_TABLES[0], "b": SEARCH_TABLES[1], "c": SEARCH_TABLES[2]},
                ).scalars()
            }
            if names == set(SEARCH_TABLES):
                table_max = session.execute(
                    text("SELECT max(id) FROM track_b_delivery_lines")
                ).scalar()
                indexed_max = session.execute(
                    text(f"SELECT max(id) FROM {SEARCH_ROWS_TABLE}")
                ).scalar()
                # Also proves this SQLite build has FTS5 with the trigram tokenizer.
                session.execute(
                    text(
                        f"SELECT rowid FROM {SEARCH_FTS_TABLE} "
                        f"WHERE {SEARCH_FTS_TABLE} MATCH :probe LIMIT 1"
                    ),
                    {"probe": _quote("abc")},
                ).all()
                ready = table_max == indexed_max
    except SQLAlchemyError:
        ready = False
    session.info[_READY_KEY] = ready
    return ready


def use_legacy_queries(session: Session) -> None:
    """Make this session ignore the side index (audits compare both paths on one file)."""

    session.info[_READY_KEY] = False


class _Unsupported(Exception):
    pass


_NOTHING = ""  # an expression part that matches no row


def _literal_expression(session: Session, column: str, literal: str) -> str:
    """Rows whose ``column`` contains ``literal`` (a superset when it has 4+ characters)."""

    if len(literal) >= 3:
        grams = dict.fromkeys(literal[index : index + 3] for index in range(len(literal) - 2))
        return f"({column} : ({' AND '.join(_quote(gram) for gram in grams)}))"
    folded = literal.lower() if literal.isascii() else literal
    if not _FOLDED_SHORT_NEEDLE.fullmatch(folded):
        raise _Unsupported(literal)  # one character, or a case the tokenizer may fold differently
    # Every two-character substring starts some trigram (values end with _END), so the rows are
    # exactly those holding any vocabulary term that starts with it.
    upper = folded[0] + chr(ord(folded[1]) + 1)
    terms = session.execute(
        text(
            f"SELECT term FROM {SEARCH_VOCAB_TABLE} "
            "WHERE col = :col AND term >= :low AND term < :high"
        ),
        {"col": column, "low": folded, "high": upper},
    ).scalars().all()
    if not terms:
        return _NOTHING
    return f"({column} : ({' OR '.join(_quote(str(term)) for term in terms)}))"


def _contains_expression(session: Session, part: Contains) -> str:
    if part.column not in SEARCH_COLUMNS:
        raise _Unsupported(part.column)
    needle = part.needle or ""
    if _END in needle:
        raise _Unsupported(needle)
    # LIKE treats % and _ inside the needle as wildcards: a matching value still contains every
    # literal piece between them, so requiring each indexable piece keeps a superset.
    pieces = []
    for literal in _LIKE_WILDCARDS.split(needle):
        if not literal:
            continue
        try:
            pieces.append(_literal_expression(session, part.column, literal))
        except _Unsupported:
            continue
    if not pieces:
        raise _Unsupported(needle)
    if _NOTHING in pieces:
        return _NOTHING
    return pieces[0] if len(pieces) == 1 else f"({' AND '.join(pieces)})"


def _expression(session: Session, part: Any) -> str:
    if isinstance(part, Contains):
        return _contains_expression(session, part)
    if isinstance(part, AnyOf):
        children = [_expression(session, child) for child in part.parts]
        kept = [child for child in children if child != _NOTHING]
        return f"({' OR '.join(kept)})" if kept else _NOTHING
    if isinstance(part, AllOf):
        children = []
        for child in part.parts:
            try:
                children.append(_expression(session, child))
            except _Unsupported:
                continue  # a conjunct left out only widens the candidate set
        if not children:
            raise _Unsupported("no indexable conjunct")
        if any(child == _NOTHING for child in children):
            return _NOTHING
        return f"({' AND '.join(children)})"
    raise _Unsupported(type(part).__name__)


def candidate_ids(session: Session, match: Any, *, order: str) -> list[int] | None:
    """Ids of rows that can satisfy ``match``, newest first ("recent") or by id ("id").

    None means the index cannot answer and the caller must run its original query.
    """

    if not search_index_ready(session):
        return None
    try:
        expression = _expression(session, match)
    except _Unsupported:
        return None
    if expression == _NOTHING:
        return []
    if order == "recent":
        sql = (
            f"SELECT r.id FROM {SEARCH_FTS_TABLE} JOIN {SEARCH_ROWS_TABLE} AS r "
            f"ON r.id = {SEARCH_FTS_TABLE}.rowid WHERE {SEARCH_FTS_TABLE} MATCH :expression "
            "ORDER BY r.transaction_date DESC, r.id DESC"
        )
    elif order == "id":
        sql = (
            f"SELECT rowid FROM {SEARCH_FTS_TABLE} WHERE {SEARCH_FTS_TABLE} MATCH :expression "
            "ORDER BY rowid"
        )
    else:
        raise ValueError(f"unknown candidate order: {order}")
    try:
        return [int(value) for value in session.execute(text(sql), {"expression": expression}).scalars()]
    except SQLAlchemyError:
        return None


def _ordered(statement, order: str):
    if order == "recent":
        return statement.order_by(
            TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc()
        )
    return statement.order_by(TrackBDeliveryLine.id)


def _fetch_in_order(
    session: Session,
    statement,
    ids: Sequence[int],
    *,
    limit: int,
    order: str,
    scalars: bool,
) -> list[Any]:
    rows: list[Any] = []
    for start in range(0, len(ids), FETCH_BATCH):
        remaining = limit - len(rows)
        if remaining <= 0:
            break
        batch = _ordered(
            statement.where(TrackBDeliveryLine.id.in_(list(ids[start : start + FETCH_BATCH]))),
            order,
        ).limit(remaining)
        result = session.scalars(batch) if scalars else session.execute(batch)
        rows.extend(result.all())
    return rows


def matching_rows(
    session: Session,
    statement,
    match: Any,
    *,
    limit: int,
    order: str = "recent",
    scalars: bool = True,
) -> list[Any]:
    """Run ``statement`` (all original WHERE terms, no ORDER BY/LIMIT) like the original query.

    ``order="recent"`` reproduces ``ORDER BY transaction_date DESC, id DESC LIMIT limit``;
    ``order="id"`` reproduces an unordered ``LIMIT limit`` over a full table scan (rowid order).
    ``match`` must be implied by the statement's own conditions: it only narrows which rows are
    read. Without a usable index the original statement runs unchanged.
    """

    ids = candidate_ids(session, match, order=order)
    session.info.setdefault(PATHS_KEY, []).append("legacy" if ids is None else "index")
    if ids is None:
        ordered = _ordered(statement, order) if order == "recent" else statement
        result = session.scalars(ordered.limit(limit)) if scalars else session.execute(
            ordered.limit(limit)
        )
        return list(result.all())
    return _fetch_in_order(session, statement, ids, limit=limit, order=order, scalars=scalars)
