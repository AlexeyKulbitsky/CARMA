"""Small durable JSON documents, shared by the host and its worker processes."""

from carma.model.json_io import read_json, write_json

__all__ = ["read_json", "write_json"]
