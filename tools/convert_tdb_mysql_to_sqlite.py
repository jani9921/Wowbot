"""Convert a TrinityCore MySQL world dump to a browsable SQLite database.

The converter deliberately parses INSERT values and binds them through SQLite
instead of trying to execute MySQL syntax as SQLite SQL.  This preserves names,
IDs, coordinates, blobs and NULL values while keeping memory use bounded.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path


CREATE_RE = re.compile(r"^CREATE TABLE `([^`]+)`")
INSERT_RE = re.compile(r"^INSERT INTO `([^`]+)` VALUES ")
COLUMN_RE = re.compile(r"^\s*`([^`]+)`\s+(.+?)(?:,)?\s*$")


def affinity(declaration: str) -> str:
    lowered = declaration.lower()
    token = declaration.lstrip().split(None, 1)[0].lower()
    token = token.split("(", 1)[0]
    # SQLite has no unsigned 64-bit integer. TEXT preserves values such as
    # 18446744073709551615 exactly instead of silently rounding them to REAL.
    if token == "bigint" and "unsigned" in lowered:
        return "TEXT"
    if token in {"tinyint", "smallint", "mediumint", "int", "integer", "bigint", "year", "bit", "bool", "boolean"}:
        return "INTEGER"
    if token in {"decimal", "numeric", "float", "double", "real"}:
        return "REAL"
    if token in {"binary", "varbinary", "tinyblob", "blob", "mediumblob", "longblob", "geometry"}:
        return "BLOB"
    return "TEXT"


def quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def schema_from_create(lines: list[str]) -> tuple[str, list[tuple[str, str]], list[tuple[str, bool, list[str]]]]:
    match = CREATE_RE.match(lines[0])
    if not match:
        raise ValueError("invalid CREATE TABLE header")
    table = match.group(1)
    columns: list[tuple[str, str]] = []
    indexes: list[tuple[str, bool, list[str]]] = []
    for line in lines[1:]:
        column = COLUMN_RE.match(line)
        if column:
            columns.append((column.group(1), affinity(column.group(2))))
            continue
        stripped = line.strip().rstrip(",")
        upper = stripped.upper()
        if upper.startswith("PRIMARY KEY"):
            names = re.findall(r"`([^`]+)`", stripped)
            if names:
                indexes.append(("primary", True, names))
        elif upper.startswith("UNIQUE KEY"):
            names = re.findall(r"`([^`]+)`", stripped)
            if len(names) >= 2:
                indexes.append((names[0], True, names[1:]))
        elif upper.startswith("KEY "):
            names = re.findall(r"`([^`]+)`", stripped)
            if len(names) >= 2:
                indexes.append((names[0], False, names[1:]))
        # FULLTEXT, SPATIAL and FOREIGN KEY have no direct lossless SQLite
        # equivalent and are intentionally omitted from this browsing copy.
    if not columns:
        raise ValueError(f"no columns found for {table}")
    return table, columns, indexes


ESCAPES = {
    "0": "\x00",
    "b": "\b",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "Z": "\x1a",
    "\\": "\\",
    "'": "'",
    '"': '"',
}


def parse_quoted(text: str, index: int) -> tuple[str, int]:
    assert text[index] == "'"
    index += 1
    output: list[str] = []
    length = len(text)
    while index < length:
        char = text[index]
        if char == "'":
            if index + 1 < length and text[index + 1] == "'":
                output.append("'")
                index += 2
                continue
            return "".join(output), index + 1
        if char == "\\" and index + 1 < length:
            escaped = text[index + 1]
            output.append(ESCAPES.get(escaped, "\\" + escaped))
            index += 2
            continue
        output.append(char)
        index += 1
    raise ValueError("unterminated MySQL string literal")


def scalar(text: str, index: int) -> tuple[object, int]:
    length = len(text)
    while index < length and text[index].isspace():
        index += 1

    binary = False
    introducer = re.match(r"_(binary|utf8mb4|utf8|latin1)\s*", text[index:], re.I)
    if introducer:
        binary = introducer.group(1).lower() == "binary"
        index += introducer.end()

    if index < length and text[index] == "'":
        value, index = parse_quoted(text, index)
        return (value.encode("utf-8", "surrogatepass") if binary else value), index

    if index + 1 < length and text[index] in "bBxX" and text[index + 1] == "'":
        kind = text[index].lower()
        value, index = parse_quoted(text, index + 1)
        if kind == "b":
            return int(value or "0", 2), index
        try:
            return bytes.fromhex(value), index
        except ValueError:
            return value, index

    start = index
    while index < length and text[index] not in ",)":
        index += 1
    token = text[start:index].strip()
    upper = token.upper()
    if upper == "NULL":
        return None, index
    if upper in {"TRUE", "FALSE"}:
        return int(upper == "TRUE"), index
    if token.lower().startswith("0x"):
        try:
            return bytes.fromhex(token[2:]), index
        except ValueError:
            return token, index
    try:
        value = int(token, 10)
        if -(2**63) <= value <= 2**63 - 1:
            return value, index
        return token, index
    except ValueError:
        pass
    try:
        return float(token), index
    except ValueError:
        return token, index


def _rows_from_insert_slow(line: str):
    values_at = line.find(" VALUES ")
    if values_at < 0:
        raise ValueError("INSERT statement has no VALUES clause")
    index = values_at + len(" VALUES ")
    length = len(line)
    while index < length:
        while index < length and (line[index].isspace() or line[index] in ",;"):
            index += 1
        if index >= length:
            return
        if line[index] != "(":
            raise ValueError(f"expected '(' at byte {index}")
        index += 1
        row: list[object] = []
        while True:
            value, index = scalar(line, index)
            row.append(value)
            while index < length and line[index].isspace():
                index += 1
            if index >= length:
                raise ValueError("unterminated INSERT tuple")
            delimiter = line[index]
            index += 1
            if delimiter == ")":
                break
            if delimiter != ",":
                raise ValueError(f"unexpected value delimiter {delimiter!r}")
        yield tuple(row)


MYSQL_STRING_RE = re.compile(r"('(?:\\.|[^'\\])*')")


def rows_from_insert(line: str):
    """Parse one mysqldump INSERT efficiently, with a strict fallback.

    Python's AST parser handles the numeric tuple structure in optimized code.
    Every quoted field is first decoded with the MySQL escape rules above and
    then represented as a Python literal, so apostrophes, newlines, NUL bytes
    and backslashes retain their actual values.
    """
    values_at = line.find(" VALUES ")
    if values_at < 0:
        raise ValueError("INSERT statement has no VALUES clause")
    body = line[values_at + len(" VALUES "):].rstrip().removesuffix(";")
    try:
        parts = MYSQL_STRING_RE.split(body)
        for index in range(1, len(parts), 2):
            value, end = parse_quoted(parts[index], 0)
            if end != len(parts[index]):
                raise ValueError("incomplete quoted token")
            parts[index] = repr(value)
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(r"\bNULL\b", "None", parts[index])
        parsed = ast.literal_eval("[" + "".join(parts) + "]")
        if not isinstance(parsed, list):
            raise ValueError("INSERT did not parse as a row list")
        for row in parsed:
            if not isinstance(row, tuple):
                raise ValueError("INSERT member is not a tuple")
            yield tuple(
                str(value) if isinstance(value, int) and not -(2**63) <= value <= 2**63 - 1 else value
                for value in row
            )
        return
    except (MemoryError, RecursionError):
        raise
    except Exception:
        # Keep support for unusual MySQL literals even if a future dump uses
        # syntax that is not also valid Python tuple syntax.
        yield from _rows_from_insert_slow(line)


def source_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_index_name(table: str, name: str, sequence: int) -> str:
    raw = f"idx_{table}_{name}_{sequence}"
    return re.sub(r"[^A-Za-z0-9_]", "_", raw)[:220]


def convert(source: Path, destination: Path, overwrite: bool) -> None:
    if destination.exists():
        if not overwrite:
            raise FileExistsError(f"destination already exists: {destination}")
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    connection = sqlite3.connect(destination)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA locking_mode=EXCLUSIVE")
    connection.execute("PRAGMA cache_size=-262144")
    connection.execute("PRAGMA foreign_keys=OFF")

    schemas: dict[str, list[tuple[str, str]]] = {}
    pending_indexes: dict[str, list[tuple[str, bool, list[str]]]] = {}
    inserted: dict[str, int] = {}
    create_lines: list[str] | None = None
    current_create = ""
    processed_bytes = 0
    last_report = 0.0
    total_size = source.stat().st_size

    try:
        with source.open("r", encoding="utf-8-sig", errors="strict", newline="", buffering=1024 * 1024) as handle:
            for line_number, line in enumerate(handle, 1):
                processed_bytes += len(line.encode("utf-8"))
                stripped = line.rstrip("\r\n")

                if create_lines is not None:
                    create_lines.append(stripped)
                    if stripped.startswith(") ENGINE=") or stripped == ");":
                        table, columns, indexes = schema_from_create(create_lines)
                        column_sql = ", ".join(
                            f"{quoted_identifier(name)} {kind}" for name, kind in columns
                        )
                        connection.execute(f"CREATE TABLE {quoted_identifier(table)} ({column_sql})")
                        schemas[table] = columns
                        pending_indexes[table] = indexes
                        inserted[table] = 0
                        current_create = table
                        create_lines = None
                    continue

                if CREATE_RE.match(stripped):
                    create_lines = [stripped]
                    continue

                insert = INSERT_RE.match(stripped)
                if not insert:
                    continue
                table = insert.group(1)
                columns = schemas.get(table)
                if columns is None:
                    raise ValueError(f"line {line_number}: INSERT precedes schema for {table}")
                placeholders = ",".join("?" for _ in columns)
                sql = f"INSERT INTO {quoted_identifier(table)} VALUES ({placeholders})"
                batch: list[tuple] = []
                connection.execute("BEGIN")
                try:
                    for row in rows_from_insert(stripped):
                        if len(row) != len(columns):
                            raise ValueError(
                                f"line {line_number}, {table}: expected {len(columns)} values, got {len(row)}"
                            )
                        batch.append(row)
                        if len(batch) >= 1000:
                            connection.executemany(sql, batch)
                            inserted[table] += len(batch)
                            batch.clear()
                    if batch:
                        connection.executemany(sql, batch)
                        inserted[table] += len(batch)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

                now = time.monotonic()
                if now - last_report >= 2.0:
                    percent = processed_bytes / total_size * 100
                    print(
                        f"[{percent:6.2f}%] {table}: {inserted[table]:,} rows; "
                        f"SQLite {destination.stat().st_size / 1024 / 1024:,.1f} MiB",
                        flush=True,
                    )
                    last_report = now

        print("Creating indexes...", flush=True)
        index_errors: list[dict] = []
        for table, definitions in pending_indexes.items():
            known = {name for name, _ in schemas[table]}
            for sequence, (name, unique, names) in enumerate(definitions):
                names = [column for column in names if column in known]
                if not names:
                    continue
                index_name = safe_index_name(table, name, sequence)
                columns_sql = ",".join(quoted_identifier(column) for column in names)
                statement = (
                    f"CREATE {'UNIQUE ' if unique else ''}INDEX {quoted_identifier(index_name)} "
                    f"ON {quoted_identifier(table)} ({columns_sql})"
                )
                try:
                    connection.execute(statement)
                except sqlite3.Error as error:
                    index_errors.append({"table": table, "index": name, "error": str(error)})
            connection.commit()

        sha256 = source_hash(source)
        connection.execute(
            "CREATE TABLE _tdb_import_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        metadata = {
            "source_file": str(source),
            "source_size_bytes": str(total_size),
            "source_sha256": sha256,
            "source_format": "MySQL dump 8.0.46 / TrinityCore world",
            "text_encoding": "utf8mb4 (decoded as UTF-8)",
            "table_count": str(len(schemas)),
            "row_count": str(sum(inserted.values())),
            "index_errors": json.dumps(index_errors, ensure_ascii=False),
            "converter": "tools/convert_tdb_mysql_to_sqlite.py",
        }
        connection.executemany(
            "INSERT INTO _tdb_import_metadata(key,value) VALUES (?,?)", metadata.items()
        )
        connection.commit()
        connection.execute("PRAGMA optimize")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        elapsed = time.monotonic() - started
        print(
            json.dumps(
                {
                    "status": "complete",
                    "destination": str(destination),
                    "size_bytes": destination.stat().st_size,
                    "tables": len(schemas),
                    "rows": sum(inserted.values()),
                    "index_errors": len(index_errors),
                    "integrity_check": integrity,
                    "elapsed_seconds": round(elapsed, 2),
                    "sha256": sha256,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    except Exception:
        connection.close()
        raise
    connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        convert(args.source, args.destination, args.overwrite)
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
