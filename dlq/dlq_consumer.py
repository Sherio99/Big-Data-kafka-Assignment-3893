from confluent_kafka import Consumer
from avro_utils import avro_deserialize


consumer_conf = {
    "bootstrap.servers": "localhost:9092",
    "group.id": "orders-dlq-group",
    "auto.offset.reset": "earliest",
}

consumer = Consumer(consumer_conf)


def main():
    consumer.subscribe(["orders_dlq"])
    print("Listening on 'orders_dlq'...")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"Error: {msg.error()}")
                continue

            headers = msg.headers()
            error_reason = None
            if headers:
                for k, v in headers:
                    if k == "error":
                        error_reason = v.decode()

            try:
                order = avro_deserialize(msg.value())
            except Exception:
                order = "<could not decode>"

            print(
                f"DLQ message | key={msg.key()} | order={order} | error={error_reason}"
            )
    except KeyboardInterrupt:
        print("Stopping DLQ consumer...")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
