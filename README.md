# 🧾 Kafka Orders – Avro, Retry & Dead Letter Queue Demo

This project is a **small end-to-end Kafka system** that shows how to:

- Produce **order** events to Kafka using **Avro** 🧬  
- Consume them and maintain a **running average** of `price` 📊  
- Implement **retry logic** for temporary failures 🔁  
- Send “poison” messages to a **Dead Letter Queue (DLQ)** ⚰️  

It’s designed as a simple learning/demo project for streaming basics and reliable message processing.

---

## 🚀 Features

- **Python producer** that generates random orders:
  ```json
  {
    "orderId": "123",
    "product": "Item3",
    "price": 49.99
  }
  ```
- **Avro serialization** for compact, schema-driven messages  
- **Main consumer**:
  - Deserializes Avro messages
  - Keeps a running average of `price`
  - Routes failures to **retry** or **DLQ**
- **Retry consumer** with `MAX_RETRIES`
- **DLQ consumer** that logs failed messages and the reason
- Local **Kafka + Zookeeper** via Docker Compose

---

## 🧱 Project Structure

```text
kafka-orders/
  avro/
    order.avsc            # Avro schema for Order messages

  consumer/
    main_consumer.py      # Main consumer: running average + sends to retry/DLQ

  dlq/
    dlq_consumer.py       # Reads from 'orders_dlq' and logs messages

  producer/
    producer.py           # Produces random orders to topic 'orders'

  retry/
    retry_consumer.py     # Handles 'orders_retry' and retries processing

  avro_utils.py           # Avro serialize/deserialize helpers

  docker-compose.yml      # Kafka + Zookeeper (Confluent images)
  requirements.txt        # Python dependencies
  README.md               # This file
```

---

## 🛠 Tech Stack

- **Language:** Python 3  
- **Messaging:** Apache Kafka  
- **Kafka client:** `confluent-kafka-python`  
- **Serialization:** Avro (`fastavro`)  
- **Containers:** Docker + Docker Compose  

---

## ✅ Prerequisites

1. **Python 3.x** installed  
2. **Docker Desktop** (with Docker Compose v2)  
3. `pip` available in your terminal

Install Python dependencies:

```bash
pip install -r requirements.txt
# or
python -m pip install -r requirements.txt
```

---

## 📦 Avro Schema

Orders use this Avro schema (`avro/order.avsc`):

```json
{
  "type": "record",
  "name": "Order",
  "namespace": "com.example.orders",
  "fields": [
    { "name": "orderId", "type": "string" },
    { "name": "product", "type": "string" },
    { "name": "price", "type": "float" }
  ]
}
```

`avro_utils.py` loads this schema once and exposes:

- `avro_serialize(record: dict) -> bytes`
- `avro_deserialize(payload: bytes) -> dict`

---

## 🧩 Kafka Topics

The system uses three topics:

| Topic         | Purpose                                                  |
|---------------|----------------------------------------------------------|
| `orders`      | Main stream of incoming orders                           |
| `orders_retry`| Temporary holding area for messages being retried        |
| `orders_dlq`  | Dead Letter Queue for messages that still fail after N tries |

`orders` is created automatically by the **producer**.  
`orders_retry` and `orders_dlq` are created when messages are first produced to them.

---

## ▶️ How to Run Everything

All commands below are run from the **project root**:

```bash
cd path/to/kafka-orders
```

### 1. Start Kafka (Docker Compose)

```bash
docker compose up -d
```

This starts:

- **Zookeeper** on port `2181`
- **Kafka** on port `9092`

Check that both are up:

```bash
docker ps
```

You should see containers named `zookeeper` and `kafka` with `STATUS` = `Up`.

To stop them later:

```bash
docker compose down
```

---

### 2. Start the DLQ Consumer (optional, but nice to watch)

Terminal #1:

```bash
python -m dlq.dlq_consumer
```

Listens on `orders_dlq` and prints messages that exhausted all retries, plus the error reason from headers.

---

### 3. Start the Retry Consumer

Terminal #2:

```bash
python -m retry.retry_consumer
```

Listens on `orders_retry` and:

- Reads `retryCount` from message headers  
- If `retryCount < MAX_RETRIES` → sends back to `orders_retry` with `retryCount + 1`  
- If `retryCount` reached `MAX_RETRIES` → sends to `orders_dlq`  

Core logic is in:

- `get_retry_count`
- `send_back_to_retry`
- `send_to_dlq`

---

### 4. Start the Main Consumer

Terminal #3:

```bash
python -m consumer.main_consumer
```

Responsibilities:

- Subscribe to `orders`
- Deserialize messages from Avro
- Update a **running average** of `price`
- Decide where to route failures:
  - temporary error → `orders_retry`
  - permanent/unknown error → `orders_dlq`

You can **simulate temporary failures** in `process_order`:

```python
if order["product"] == "Item3":
    raise RuntimeError("Simulated temporary error")
```

---

### 5. Start the Producer

Terminal #4:

```bash
python -m producer.producer
```

The producer:

- Generates random orders with fields `orderId`, `product`, `price`
- Serializes them with Avro (`avro_serialize`)
- Produces them to topic `orders` in an infinite loop (1 message/second)
- Triggers auto-creation of the `orders` topic on the broker

---

## 🎬 Demo Scenario (Good for Presentations)

1. **Start Kafka**  

   ```bash
   docker compose up -d
   ```

2. **Start all consumers** in separate terminals:

   ```bash
   python -m dlq.dlq_consumer
   python -m retry.retry_consumer
   python -m consumer.main_consumer
   ```

3. **Start the producer**:

   ```bash
   python -m producer.producer
   ```

4. **Show running average**  
   - Highlight `main_consumer` output:
     - Each order processed
     - The updated running average price

5. **Show retry & DLQ behavior**

   - Uncomment the simulated error in `process_order` (for `Item3`)
   - Restart `main_consumer`
   - Point out:
     - Some orders fail and are sent to `orders_retry`
     - `retry_consumer` logs retry attempts
     - Messages that keep failing after `MAX_RETRIES` appear in `dlq_consumer` output

6. **Stop everything**

   - Stop each Python process with `Ctrl + C`
   - Then stop Kafka:

     ```bash
     docker compose down
     ```

---

## 🧠 Where Retry & DLQ Logic Lives

**Main consumer** – `consumer/main_consumer.py`

- `process_order(order)`  
  Business logic + running average. Can raise temporary errors.
- `send_to_retry(msg, error_msg, retry_count)`  
  Adds/increments `retryCount` header and produces to `orders_retry`.
- `send_to_dlq(msg, error_msg)`  
  Attaches `error` header and produces to `orders_dlq`.

**Retry consumer** – `retry/retry_consumer.py`

- Reads `orders_retry`  
- Uses `get_retry_count(headers)` to parse `retryCount`.
- If `retryCount + 1 < MAX_RETRIES` → `send_back_to_retry`
- Else → `send_to_dlq`

**DLQ consumer** – `dlq/dlq_consumer.py`

- Reads `orders_dlq`  
- Tries to Avro-decode the message  
- Prints key, decoded order (or `<could not decode>`) and `error` header  

---

## 🧪 Useful Commands

```bash
# Show running containers
docker ps

# View Kafka container logs
docker logs kafka --tail 50

# Kill all Python processes (one by one)
Ctrl + C

# Clean shutdown of Kafka/Zookeeper
docker compose down
```

---

## 📚 Possible Extensions

Ideas if you want to improve the project further:

- Expose metrics (e.g., average price) via a REST API or Prometheus
- Add unit tests for `process_order`, `get_retry_count`, etc.
- Add JSON schema or Protobuf versions and compare
- Use a Kafka Streams / Faust / ksqlDB style aggregation instead of in-memory

---

## 👤 Author

- Name: Dias B.R.S.T – _undergraduate / developer_
- Reg. no.: EG/2020/3893  
- GitHub: [https://github.com/Sherio99/Big-Data-kafka-Assignment-3893]
