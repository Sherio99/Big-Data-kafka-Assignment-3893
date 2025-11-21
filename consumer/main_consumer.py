from confluent_kafka import Consumer, Producer, KafkaException
from avro_utils import avro_deserialize

# Kafka consumer config
consumer_conf = {
    "bootstrap.servers": "localhost:9092",
    "group.id": "orders-consumer-group",
    "auto.offset.reset": "earliest",
}

producer_conf = {
    "bootstrap.servers": "localhost:9092",
}

consumer = Consumer(consumer_conf)
producer = Producer(producer_conf)

TOTAL_SUM = 0.0
TOTAL_COUNT = 0

MAX_RETRIES = 3  # how many times we allow retry


def process_order(order: dict):
    """
    Business logic:
    - update running average of price
    - you can simulate temporary errors here
    """
    global TOTAL_SUM, TOTAL_COUNT

    # To simulate temporary errors, UNCOMMENT this block:
    # if order["product"] == "Item3":
    #     raise RuntimeError("Simulated temporary error")

    price = order["price"]
    product = order["product"]   # <--- get product name

    TOTAL_SUM += price
    TOTAL_COUNT += 1

    avg_price = TOTAL_SUM / TOTAL_COUNT
    print(
        f"Processed order {order['orderId']} | product={product} | "
        f"price={price} | running average={avg_price:.2f}"
    )


def send_to_retry(msg, error_msg: str, retry_count: int = 0):
    headers = [
        ("retryCount", str(retry_count + 1).encode()),
        ("error", error_msg.encode()),
    ]
    producer.produce(
        topic="orders_retry",
        key=msg.key(),
        value=msg.value(),
        headers=headers,
    )
    producer.flush()
    print(f"Sent to retry (attempt {retry_count + 1})")


def send_to_dlq(msg, error_msg: str):
    headers = [("error", error_msg.encode())]
    producer.produce(
        topic="orders_dlq",
        key=msg.key(),
        value=msg.value(),
        headers=headers,
    )
    producer.flush()
    print(f"Sent to DLQ due to error: {error_msg}")


def main():
    consumer.subscribe(["orders"])
    print("Listening on topic 'orders'...")

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                raise KafkaException(msg.error())

            try:
                order = avro_deserialize(msg.value())
                process_order(order)
                consumer.commit(msg)  # success
            except RuntimeError as e:
                # temporary error → retry topic
                send_to_retry(msg, str(e), retry_count=0)
                consumer.commit(msg)
            except Exception as e:
                # permanent / unknown error → DLQ
                send_to_dlq(msg, str(e))
                consumer.commit(msg)
    except KeyboardInterrupt:
        print("Stopping consumer...")
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
