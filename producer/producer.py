import random
import time

from confluent_kafka import Producer
from avro_utils import avro_serialize

# Kafka configuration
producer_conf = {
    "bootstrap.servers": "localhost:9092"
}

producer = Producer(producer_conf)


def delivery_report(err, msg):
    """Called once for each message to report delivery result."""
    if err is not None:
        print(f"Delivery failed for key={msg.key()}: {err}")
    else:
        print(
            f"Message delivered to {msg.topic()} "
            f"[{msg.partition()}] offset {msg.offset()}"
        )


def generate_order(order_id: int) -> dict:
    return {
        "orderId": str(order_id),
        "product": f"Item{random.randint(1, 5)}",
        "price": round(random.uniform(10.0, 100.0), 2),
    }


def main():
    max_messages = 40          # production was limited to 40 due to continuous production to check the order id, product and price produced by producer matches with consumer
    order_id = 1

    try:
        while order_id <= max_messages:
            order = generate_order(order_id)
            value_bytes = avro_serialize(order)

            producer.produce(
                topic="orders",
                key=order["orderId"].encode(),
                value=value_bytes,
                callback=delivery_report,
            )

            # Trigger callbacks
            producer.poll(0)

            print(f"Sent order: {order}")
            order_id += 1
            time.sleep(1)  # 1 order per second
    except KeyboardInterrupt:
        print("Stopping producer early...")
    finally:
        # This make sure any remaining messages are sent
        producer.flush()
        print("Producer finished.")


if __name__ == "__main__":
    main()
