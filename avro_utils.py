import io
import json
from fastavro import schemaless_writer, schemaless_reader

# Load schema once
with open("avro/order.avsc") as f:
    ORDER_SCHEMA = json.load(f)

def avro_serialize(record: dict) -> bytes:
    """Convert a Python dict to Avro bytes."""
    buf = io.BytesIO()
    schemaless_writer(buf, ORDER_SCHEMA, record)
    return buf.getvalue()

def avro_deserialize(payload: bytes) -> dict:
    """Convert Avro bytes back into a Python dict."""
    buf = io.BytesIO(payload)
    return schemaless_reader(buf, ORDER_SCHEMA)
