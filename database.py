import os
from datetime import datetime
from contextlib import contextmanager
from decimal import Decimal
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor


class Database:
    def __init__(self, database_url=None):
        self.database_url = database_url or os.getenv("DATABASE_URL", "")
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is missing. Attach Heroku Postgres.")

    def connect(self):
        return psycopg2.connect(
            self.database_url,
            sslmode="require",
            cursor_factory=RealDictCursor,
        )

    @contextmanager
    def connection(self):
        con = self.connect()
        try:
            with con:
                yield con
        finally:
            con.close()

    def initialize(self):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    supplier TEXT NOT NULL DEFAULT '',
                    cost NUMERIC(12,2) NOT NULL CHECK(cost > 0),
                    status TEXT NOT NULL DEFAULT 'available'
                        CHECK(status IN ('available','sold')),
                    added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS customers (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sales (
                    id BIGSERIAL PRIMARY KEY,
                    inventory_id BIGINT NOT NULL UNIQUE REFERENCES inventory(id),
                    customer_id BIGINT REFERENCES customers(id),
                    item_name TEXT NOT NULL UNIQUE,
                    supplier TEXT NOT NULL DEFAULT '',
                    cost NUMERIC(12,2) NOT NULL,
                    price NUMERIC(12,2) NOT NULL,
                    profit NUMERIC(12,2) NOT NULL,
                    sold_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expenses (
                    id BIGSERIAL PRIMARY KEY,
                    description TEXT NOT NULL,
                    amount NUMERIC(12,2) NOT NULL CHECK(amount > 0),
                    created_at TEXT NOT NULL
                );
                ALTER TABLE inventory ADD COLUMN IF NOT EXISTS supplier TEXT NOT NULL DEFAULT '';
                """)

    def add_inventory(self, email, supplier, cost):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    """INSERT INTO inventory(name,supplier,cost,status,added_at)
                    VALUES(%s,%s,%s,'available',%s) RETURNING id""",
                    (email, supplier, cost, now),
                )
                return cur.fetchone()["id"]

    def available_inventory(self):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id,name,supplier,cost FROM inventory WHERE status='available' ORDER BY id"
                )
                return cur.fetchall()

    def get_available_item(self, item_id):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id,name,supplier,cost FROM inventory WHERE id=%s AND status='available'",
                    (item_id,),
                )
                return cur.fetchone()

    def record_sale(self, item_id, price, customer_name=""):
        now = datetime.now().isoformat(timespec="seconds")
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT id,name,supplier,cost FROM inventory WHERE id=%s AND status='available' FOR UPDATE",
                    (item_id,),
                )
                item = cur.fetchone()
                if not item:
                    return None
                customer_id = None
                if customer_name:
                    cur.execute(
                        """INSERT INTO customers(name,created_at) VALUES(%s,%s)
                        ON CONFLICT(name) DO NOTHING""",
                        (customer_name, now),
                    )
                    cur.execute("SELECT id FROM customers WHERE name=%s", (customer_name,))
                    customer_id = cur.fetchone()["id"]
                cost = Decimal(str(item["cost"]))
                profit = price - cost
                cur.execute("UPDATE inventory SET status='sold' WHERE id=%s", (item_id,))
                cur.execute(
                    """INSERT INTO sales
                    (inventory_id,customer_id,item_name,cost,price,profit,sold_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (item_id, customer_id, item["name"], cost, price, profit, now),
                )
                return {
                    "item_id": item_id, "name": item["name"],
                    "customer": customer_name, "supplier": item["supplier"], "cost": cost,
                    "price": price, "profit": profit,
                }

    def add_expense(self, description, amount):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    "INSERT INTO expenses(description,amount,created_at) VALUES(%s,%s,%s)",
                    (description, amount, datetime.now().isoformat(timespec="seconds")),
                )

    def report(self, start_date):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) AS n, COALESCE(SUM(price),0) AS revenue,
                    COALESCE(SUM(cost),0) AS cost, COALESCE(SUM(profit),0) AS gross
                    FROM sales WHERE substring(sold_at,1,10) >= %s""",
                    (start_date,),
                )
                sales = cur.fetchone()
                cur.execute(
                    "SELECT COALESCE(SUM(amount),0) AS total FROM expenses WHERE substring(created_at,1,10) >= %s",
                    (start_date,),
                )
                expenses = cur.fetchone()["total"]
                cur.execute("SELECT COUNT(*) AS n FROM inventory WHERE status='available'")
                stock = cur.fetchone()["n"]
        return {
            "count": sales["n"], "revenue": sales["revenue"],
            "cost": sales["cost"], "gross_profit": sales["gross"],
            "expenses": expenses, "net_profit": sales["gross"] - expenses,
            "stock": stock,
        }

    def sales_history(self, limit=20):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute(
                    """SELECT s.id,s.item_name AS name,s.price,s.profit,s.sold_at,
                    i.supplier,COALESCE(c.name,'') AS customer
                    FROM sales s JOIN inventory i ON i.id=s.inventory_id
                    LEFT JOIN customers c ON c.id=s.customer_id
                    ORDER BY s.id DESC LIMIT %s""",
                    (limit,),
                )
                return cur.fetchall()

    def customer_history(self):
        with self.connection() as con:
            with con.cursor() as cur:
                cur.execute("""
                    SELECT c.name AS customer, COUNT(s.id) AS orders,
                    COALESCE(SUM(s.price),0) AS revenue
                    FROM customers c JOIN sales s ON s.customer_id=c.id
                    GROUP BY c.id ORDER BY revenue DESC
                """)
                return cur.fetchall()
