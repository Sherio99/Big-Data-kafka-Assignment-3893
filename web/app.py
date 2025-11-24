from flask import Flask, render_template, request
import json
import os

app = Flask(__name__)

# stats.json lives one level above the web/ folder
STATS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "stats.json")
)


def load_stats_from_file():
    """Load stats.json written by main_consumer.py, or return None."""
    if not os.path.exists(STATS_PATH):
        return None

    try:
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading stats.json: {e}")
        return None


def compute_product_aggregates(orders):
    """
    Build aggregates per product:
    - average price
    - count
    - last timestamp (if present in order["time"])
    """
    agg = {}
    for o in orders or []:
        product = o.get("product")
        if not product:
            continue

        price = float(o.get("price", 0))
        ts = o.get("time")  # optional

        if product not in agg:
            agg[product] = {
                "product": product,
                "total_price": 0.0,
                "count": 0,
                "last_time": ts,
            }

        entry = agg[product]
        entry["total_price"] += price
        entry["count"] += 1

        if ts is not None:
            if entry["last_time"] is None or ts > entry["last_time"]:
                entry["last_time"] = ts

    result = []
    for data in agg.values():
        avg = data["total_price"] / data["count"] if data["count"] else 0.0
        result.append(
            {
                "product": data["product"],
                "avg_price": avg,
                "count": data["count"],
                "last_time": data["last_time"],
            }
        )

    return sorted(result, key=lambda x: x["product"])


def get_data():
    """
    Load stats + orders + real retry/DLQ lists from stats.json.
    Fallback to empty data if file doesn't exist yet.
    """
    stats_json = load_stats_from_file()

    if stats_json:
        orders = stats_json.get("recent_orders", [])
        retry_messages = stats_json.get("retry_messages", [])
        dlq_messages = stats_json.get("dlq_messages", [])

        # Use counts from the actual lists so UI is always consistent
        stats = {
            "total_orders": stats_json.get("total_orders", len(orders)),
            "avg_price": stats_json.get("avg_price", 0.0),
            "retry_count": len(retry_messages),
            "dlq_count": len(dlq_messages),
        }
    else:
        orders = []
        retry_messages = []
        dlq_messages = []
        stats = {
            "total_orders": 0,
            "avg_price": 0.0,
            "retry_count": 0,
            "dlq_count": 0,
        }

    product_aggregates = compute_product_aggregates(orders)

    return stats, orders, retry_messages, dlq_messages, product_aggregates


@app.route("/")
def index():
    stats, orders, retry_messages, dlq_messages, product_aggregates = get_data()

    # --- Recent orders pagination (ALL orders from stats.json) ---
    per_page = 10
    page = request.args.get("page", "1")
    try:
        page = int(page)
    except ValueError:
        page = 1

    # newest first
    orders_sorted = list(reversed(orders))
    total_orders = len(orders_sorted)
    total_pages = max(1, (total_orders + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    page_orders = orders_sorted[start:end]

    # show latest retries / dlq first (you can slice if you only want top N)
    retry_messages_sorted = list(reversed(retry_messages))
    dlq_messages_sorted = list(reversed(dlq_messages))

    return render_template(
        "index.html",
        stats=stats,
        orders=page_orders,
        all_orders_count=total_orders,
        current_page=page,
        total_pages=total_pages,
        retry_messages=retry_messages_sorted,
        dlq_messages=dlq_messages_sorted,
        product_aggregates=product_aggregates,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
