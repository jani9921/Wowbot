"""Recover one public CDN executable for offline comparison; never install/run it.

Requires the existing cascette_tools checkout (passed explicitly). Content hashes
come from the retained Blizzard 70448 build config and the previous port audit.
The hashes below identify public CDN content, not authentication/session keys.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import urllib.request


EXPECTED_SHA256 = "1c51e68c00e7183c2c187606d2c443c27252a629406454de4afec336e8c5753a"
EXPECTED_SIZE = 80_834_256
CONTENT_HASH = "b36ac789caf3c72f1227021d2591009b"
ENCODING_HASH = "6e9260e140bd5f5b116d47229e937993"
ENCODING_CONTENT_HASH = "c36d0a7a0645d12c52932ec8c8f7fea2"


def download(content_hash: str, limit: int) -> bytes:
    url = ("https://level3.ssl.blizzard.com/tpr/wow/data/"
           f"{content_hash[:2]}/{content_hash[2:4]}/{content_hash}")
    print(f"Public CDN read: {content_hash}", flush=True)
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("CDN response exceeds expected size limit")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cascette-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        if hashlib.sha256(output.read_bytes()).hexdigest() != EXPECTED_SHA256:
            raise ValueError("different output already exists; refusing overwrite")
        print("Already recovered and hash-verified:", output)
        return
    root = args.cascette_root.resolve()
    sys.path[:0] = [str(root), str(root / "_deps")]
    from cascette_tools.formats.blte import decompress_blte
    from cascette_tools.formats.encoding import EncodingParser

    encoding = decompress_blte(download(ENCODING_HASH, 190_000_000))
    if hashlib.md5(encoding).hexdigest() != ENCODING_CONTENT_HASH:
        raise ValueError("encoding content hash mismatch")
    encoding_parser = EncodingParser()
    index = encoding_parser.parse(encoding)
    hashes = encoding_parser.find_content_key(encoding, index, bytes.fromhex(CONTENT_HASH))
    if not hashes:
        raise ValueError("70448 Windows executable not found in encoding index")
    print("Executable CDN hashes:", [value.hex() for value in hashes], flush=True)
    decoded = decompress_blte(download(hashes[0].hex(), 110_000_000))
    if (len(decoded) != EXPECTED_SIZE
            or hashlib.md5(decoded).hexdigest() != CONTENT_HASH
            or hashlib.sha256(decoded).hexdigest() != EXPECTED_SHA256):
        raise ValueError("70448 reference size/content/SHA-256 verification failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(decoded)
    print(f"Recovered: {output}; SHA-256={EXPECTED_SHA256}; executed=False")


if __name__ == "__main__":
    main()
