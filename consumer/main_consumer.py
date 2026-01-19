import json
import os
import time

from confluent_kafka import Consumer, Producer, KafkaException, KafkaError
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

# maximum attempts for a temporary failure (within this consumer)
MAX_ATTEMPTS = 3

RETRY_COUNT = 0  # how many orders needed at least one retry
DLQ_COUNT = 0    # how many orders we sent to orders_dlq

LAST_AVG = 0.0
ALL_ORDERS = []        # store ALL successfully processed orders for the dashboard

# Lists for dashboard
RETRY_MESSAGES = []    # each: {orderId, product, price, attempt, error, time}
DLQ_MESSAGES = []      # each: {orderId, payload, error, time}

STATS_FILE = "stats.json"   # written in project root


def write_stats():
    """Write current stats (orders + retry/DLQ info) to stats.json."""
    stats = {
        "total_orders": TOTAL_COUNT,
        "avg_price": LAST_AVG,
        "retry_count": RETRY_COUNT,
        "dlq_count": DLQ_COUNT,
        "recent_orders": ALL_ORDERS,
        "retry_messages": RETRY_MESSAGES,
        "dlq_messages": DLQ_MESSAGES,
    }

    try:
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        print(f"Could not write stats.json: {e}")


def record_success(order: dict):
    """Update average + append order for dashboard."""
    global LAST_AVG, ALL_ORDERS

    if TOTAL_COUNT > 0:
        LAST_AVG = TOTAL_SUM / TOTAL_COUNT
    else:
        LAST_AVG = 0.0

    ALL_ORDERS.append(
        {
            "orderId": order["orderId"],
            "product": order["product"],
            "price": float(order["price"]),
            # "time": int(time.time() * 1000),  # optional
        }
    )


def process_order(order: dict, attempt: int):
    """
    Business logic:
    - update running average of price
    - simulate temporary + permanent errors so we see retries & DLQ

    For demo:
    - Item1: temporary error on first attempt, then succeeds on later attempts.
    - Item2: permanent error on every attempt, goes to DLQ.
    """
    global TOTAL_SUM, TOTAL_COUNT

    # Simulate a temporary error: only on first attempt
    if order["product"] == "Item1" and attempt == 1:
        raise RuntimeError("Simulated temporary error on first attempt")

    # Simulate a permanent error: will be sent directly to DLQ
    if order["product"] == "Item2":
        raise ValueError("Simulated permanent error")

    # Normal successful processing for other products (Item3/4/5)
    price = order["price"]
    product = order["product"]

    TOTAL_SUM += price
    TOTAL_COUNT += 1

    avg_price = TOTAL_SUM / TOTAL_COUNT
    print(
        f"Processed order {order['orderId']} | product={product} | "
        f"price={price} | running average={avg_price:.2f}"
    )


def send_to_dlq(msg, error_msg: str, attempts: int):
    """Send to orders_dlq and record a real DLQ event."""
    global DLQ_COUNT, DLQ_MESSAGES
    DLQ_COUNT += 1

    order = None
    try:
        order = avro_deserialize(msg.value())
    except Exception:
        pass

    if order is not None:
        payload_str = json.dumps(order)
    else:
        try:
            payload_str = msg.value().decode("utf-8")
        except Exception:
            payload_str = str(msg.value())

    timestamp = int(time.time() * 1000)

    DLQ_MESSAGES.append(
        {
            "orderId": order["orderId"] if order else None,
            "payload": payload_str,
            "error": f"{error_msg} (after {attempts} attempt(s))",
            "time": timestamp,
        }
    )

    headers = [
        ("error", error_msg.encode()),
        ("attempts", str(attempts).encode()),
    ]
    producer.produce(
        topic="orders_dlq",
        key=msg.key(),
        value=msg.value(),
        headers=headers,
    )
    producer.flush()
    print(f"Sent to DLQ after {attempts} attempt(s): {error_msg}")


def handle_with_retries(msg, order: dict):
    """
    Try to process an order, retrying temporary failures (RuntimeError)
    up to MAX_ATTEMPTS times. If it keeps failing, send to DLQ.

    If it finally succeeds, print how many attempts were needed and
    record that in RETRY_MESSAGES for the dashboard.
    """
    global RETRY_COUNT

    attempt = 0
    last_error = None
    had_temporary_error = False

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        try:
            # optional simple backoff
            if attempt > 1:
                time.sleep(1)

            # may raise RuntimeError / ValueError / ...
            process_order(order, attempt)
            record_success(order)  # only on success

            # If we had at least one temporary error, record it
            if had_temporary_error:
                RETRY_COUNT += 1
                timestamp = int(time.time() * 1000)
                RETRY_MESSAGES.append(
                    {
                        "orderId": order["orderId"],
                        "product": order["product"],
                        "price": float(order["price"]),
                        "attempt": attempt,
                        "error": str(last_error),
                        "time": timestamp,
                    }
                )

            print(
                f"Order {order['orderId']} successfully processed "
                f"after {attempt} attempt(s)"
            )
            consumer.commit(msg)
            return

        except RuntimeError as e:
            # Treat RuntimeError as temporary: retry
            had_temporary_error = True
            last_error = e
            print(
                f"Temporary error processing order {order['orderId']} "
                f"on attempt {attempt}: {e}"
            )
            if attempt >= MAX_ATTEMPTS:
                # exhausted retries → DLQ
                send_to_dlq(msg, str(e), attempt)
                consumer.commit(msg)
                return
            # otherwise loop again

        except Exception as e:
            # Any other error is considered permanent → no retries
            last_error = e
            print(
                f"Permanent error processing order {order['orderId']} "
                f"on attempt {attempt}: {e}"
            )
            send_to_dlq(msg, str(e), attempt)
            consumer.commit(msg)
            return


def main():
    global TOTAL_SUM, TOTAL_COUNT, RETRY_COUNT, DLQ_COUNT, LAST_AVG
    global ALL_ORDERS, RETRY_MESSAGES, DLQ_MESSAGES

    # Reset all in-memory state for a "new production run"
    TOTAL_SUM = 0.0
    TOTAL_COUNT = 0
    RETRY_COUNT = 0
    DLQ_COUNT = 0
    LAST_AVG = 0.0
    ALL_ORDERS = []
    RETRY_MESSAGES = []
    DLQ_MESSAGES = []

    # Remove previous stats.json so dashboard starts fresh
    if os.path.exists(STATS_FILE):
        try:
            os.remove(STATS_FILE)
            print("Previous stats.json removed.")
        except Exception as e:
            print(f"Could not remove stats.json: {e}")

    consumer.subscribe(["orders"])
    print("Listening on topic 'orders'...")

    # initial empty stats so the dashboard can load even before messages
    write_stats()

    try:
        while True:
            msg = consumer.poll(1.0)

            if msg is None:
                continue

            if msg.error():
                # if topic doesn't exist yet, just wait and try again
                if msg.error().code() == KafkaError.UNKNOWN_TOPIC_OR_PART:
                    print("Topic 'orders' not found yet. Waiting for producer to create it...")
                    time.sleep(2)
                    continue
                raise KafkaException(msg.error())

            try:
                order = avro_deserialize(msg.value())
            except Exception as e:
                # Cannot even decode → send straight to DLQ (1 attempt)
                print(f"Failed to deserialize message: {e}")
                send_to_dlq(msg, f"Deserialization error: {e}", attempts=1)
                consumer.commit(msg)
                write_stats()
                continue

            # Handle the order with retry logic
            handle_with_retries(msg, order)
            write_stats()

    except KeyboardInterrupt:
        print("Stopping consumer...")
    finally:
        consumer.close()
        write_stats()  # final write on shutdown


if __name__ == "__main__":
    main()
