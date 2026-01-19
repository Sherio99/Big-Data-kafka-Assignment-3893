import time

from confluent_kafka import Consumer, Producer
from avro_utils import avro_deserialize

# Kafka configs for retry consumer + producer
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

# We allow up to 3 retry attempts on the retry topic.
# (Original processing in main_consumer is attempt 0.)
MAX_RETRIES = 3


def get_retry_count(headers):
    """Read retryCount header from message, default 0."""
    if not headers:
        return 0
    for key, value in headers:
        if key == "retryCount":
            return int(value.decode())
    return 0


def process_order(order: dict, retry_count: int):
    """
    The real business logic for a retried message.
    For now we just print, but you can add your own logic.
    """
    print(
        f"Successfully processed order {order['orderId']} "
        f"after {retry_count} retry attempt(s)"
    )


def send_back_to_retry(msg, error_msg, retry_count):
    """
    Re-queue the message back to orders_retry with retryCount+1.
    """
    headers = [
        ("retryCount", str(retry_count + 1).encode()),
        ("error", error_msg.encode()),
    ]
    producer.produce(
        "orders_retry",
        key=msg.key(),
        value=msg.value(),
        headers=headers,
    )
    producer.flush()
    print(f"Re-sent to retry (attempt {retry_count + 1}) due to: {error_msg}")


def send_to_dlq(msg, error_msg, final_retry_count):
    """
    Send the message to DLQ when it still fails after MAX_RETRIES.
    """
    headers = [
        ("error", error_msg.encode()),
        ("finalRetryCount", str(final_retry_count).encode()),
    ]
    producer.produce(
        "orders_dlq",
        key=msg.key(),
        value=msg.value(),
        headers=headers,
    )
    producer.flush()
    print(
        f"Sent to DLQ after {final_retry_count} retry attempt(s): {error_msg}"
    )


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

            retry_count = get_retry_count(msg.headers())  # 1, 2, 3...

            try:
                # Simple backoff before retrying
                time.sleep(2)

                # Try to decode and process the order
                order = avro_deserialize(msg.value())

                # If this succeeds, we consider the message recovered
                process_order(order, retry_count)
                consumer.commit(msg)

            except Exception as e:
                # Failed again during this retry attempt
                if retry_count >= MAX_RETRIES:
                    # We've already reached the max allowed retries on this topic.
                    # Treat this as a permanent failure and send to DLQ.
                    send_to_dlq(msg, str(e), retry_count)
                    consumer.commit(msg)
                else:
                    # Not yet at max retries → send back to retry topic
                    send_back_to_retry(msg, str(e), retry_count)
                    consumer.commit(msg)

    except KeyboardInterrupt:
        print("Stopping retry consumer...")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
