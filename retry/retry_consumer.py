import time
from confluent_kafka import Consumer, Producer
from avro_utils import avro_deserialize

consumer_conf = {
    "bootstrap.servers": "localhost:9092",
    "group.id": "orders-retry-group",
    "auto.offset.reset": "earliest",
}

producer_conf = {
    "bootstrap.servers": "localhost:9092",
}

consumer = Consumer(consumer_conf)
producer = Producer(producer_conf)

MAX_RETRIES = 3


def get_retry_count(headers):
    if not headers:
        return 0
    for key, value in headers:
        if key == "retryCount":
            return int(value.decode())
    return 0


def send_back_to_retry(msg, error_msg, retry_count):
    headers = [
        ("retryCount", str(retry_count + 1).encode()),
        ("error", error_msg.encode()),
    ]
    producer.produce("orders_retry", key=msg.key(), value=msg.value(), headers=headers)
    producer.flush()
    print(f"Re-sent to retry (attempt {retry_count + 1})")


def send_to_dlq(msg, error_msg):
    headers = [("error", error_msg.encode())]
    producer.produce("orders_dlq", key=msg.key(), value=msg.value(), headers=headers)
    producer.flush()
    print(f"Sent to DLQ from retry consumer: {error_msg}")


def main():
    consumer.subscribe(["orders_retry"])
    print("Listening on 'orders_retry'...")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                print(f"Error: {msg.error()}")
                continue

            retry_count = get_retry_count(msg.headers())
            try:
                time.sleep(2)  # simple backoff
                order = avro_deserialize(msg.value())
                print(f"Retrying order {order['orderId']} (attempt {retry_count + 1})")
                # Here you could re-run real processing.
                consumer.commit(msg)
            except Exception as e:
                if retry_count + 1 >= MAX_RETRIES:
                    send_to_dlq(msg, str(e))
                    consumer.commit(msg)
                else:
                    send_back_to_retry(msg, str(e), retry_count)
                    consumer.commit(msg)
    except KeyboardInterrupt:
        print("Stopping retry consumer...")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
