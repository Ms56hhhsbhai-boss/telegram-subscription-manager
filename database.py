import os
from datetime import datetime
from decimal import Decimal
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError


class Database:
    """MongoDB implementation of the existing SCARFACE CONTROL database API."""
    def __init__(self, database_url=None):
        self.database_url = database_url or os.getenv("MONGODB_URI", "")
        if not self.database_url:
            raise RuntimeError("MONGODB_URI is missing. Set your MongoDB Atlas connection string.")
        self.client = MongoClient(self.database_url, serverSelectionTimeoutMS=15000)
        db_name = os.getenv("MONGODB_DATABASE", "scarface_control")
        self.db = self.client[db_name]
        self.inventory = self.db.inventory
        self.sales = self.db.sales
        self.customers = self.db.customers
        self.expenses = self.db.expenses
        self.counters = self.db.counters

    def initialize(self):
        self.client.admin.command("ping")
        self.inventory.create_index("name", unique=True)
        self.inventory.create_index([("status", 1), ("id", 1)])
        self.sales.create_index([("id", -1)])
        self.customers.create_index("name", unique=True)
        self.expenses.create_index("created_at")

    def _next_id(self, key):
        doc = self.counters.find_one_and_update(
            {"_id": key}, {"$inc": {"seq": 1}}, upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return doc["seq"]

    @staticmethod
    def _money(value):
        return Decimal(str(value))

    def reset_all_data(self):
        counts = {
            "inventory": self.inventory.count_documents({}),
            "sales": self.sales.count_documents({}),
            "customers": self.customers.count_documents({}),
            "expenses": self.expenses.count_documents({}),
        }
        self.inventory.delete_many({})
        self.sales.delete_many({})
        self.customers.delete_many({})
        self.expenses.delete_many({})
        self.counters.delete_many({})
        return counts

    def add_inventory(self, email, supplier, cost=0, photo_file_id=None):
        doc = {
            "id": self._next_id("inventory"), "name": email,
            "supplier": supplier, "cost": float(self._money(cost)),
            "status": "available", "added_at": datetime.now().isoformat(timespec="seconds"),
            "photo_file_id": photo_file_id,
        }
        self.inventory.insert_one(doc)
        return doc["id"]

    def available_inventory(self):
        return list(self.inventory.find(
            {"status": "available"},
            {"_id": 0, "id": 1, "name": 1, "supplier": 1, "cost": 1, "photo_file_id": 1},
        ).sort("id", 1))

    def all_inventory(self, limit=60):
        """Return both available and sold accounts with their purchase details."""
        return list(self.inventory.find(
            {},
            {"_id": 0, "id": 1, "name": 1, "supplier": 1, "cost": 1,
             "status": 1, "added_at": 1, "photo_file_id": 1},
        ).sort("id", -1).limit(int(limit)))

    def get_available_item(self, item_id):
        return self.inventory.find_one(
            {"id": int(item_id), "status": "available"},
            {"_id": 0, "id": 1, "name": 1, "supplier": 1, "cost": 1, "photo_file_id": 1},
        )

    def record_sale(self, item_id, buying_price, selling_price, customer_name="", warranty="No Warranty"):
        item = self.inventory.find_one_and_update(
            {"id": int(item_id), "status": "available"},
            {"$set": {"status": "sold"}}, return_document=ReturnDocument.BEFORE,
        )
        if not item:
            return None
        now = datetime.now().isoformat(timespec="seconds")
        cost = self._money(buying_price)
        price = self._money(selling_price)
        profit = price - cost
        self.inventory.update_one({"id": int(item_id)}, {"$set": {"cost": float(cost)}})
        if customer_name:
            self.customers.update_one(
                {"name": customer_name},
                {"$setOnInsert": {"id": self._next_id("customer"), "name": customer_name, "created_at": now}},
                upsert=True,
            )
        sale_id = self._next_id("sales")
        self.sales.insert_one({
            "id": sale_id, "inventory_id": int(item_id), "customer": customer_name,
            "item_name": item["name"], "supplier": item.get("supplier", ""),
            "photo_file_id": item.get("photo_file_id"), "cost": float(cost),
            "price": float(price), "profit": float(profit), "warranty": warranty, "sold_at": now,
        })
        return {"item_id": int(item_id), "name": item["name"], "customer": customer_name,
                "supplier": item.get("supplier", ""), "cost": cost, "price": price,
                "profit": profit, "warranty": warranty}

    def add_expense(self, description, amount):
        self.expenses.insert_one({
            "id": self._next_id("expense"), "description": description,
            "amount": float(self._money(amount)), "created_at": datetime.now().isoformat(timespec="seconds"),
        })

    def report(self, start_date):
        sales = list(self.sales.find({"sold_at": {"$gte": start_date}}))
        expenses = list(self.expenses.find({"created_at": {"$gte": start_date}}))
        revenue = sum((self._money(x["price"]) for x in sales), Decimal("0"))
        cost = sum((self._money(x["cost"]) for x in sales), Decimal("0"))
        gross = sum((self._money(x["profit"]) for x in sales), Decimal("0"))
        expense_total = sum((self._money(x["amount"]) for x in expenses), Decimal("0"))
        return {"count": len(sales), "revenue": revenue, "cost": cost,
                "gross_profit": gross, "expenses": expense_total,
                "net_profit": gross - expense_total,
                "stock": self.inventory.count_documents({"status": "available"})}

    def sales_history(self, limit=20):
        rows = list(self.sales.find({}, {"_id": 0}).sort("id", -1).limit(int(limit)))
        for row in rows:
            row["name"] = row.get("item_name", "")
        return rows

    def customer_history(self):
        pipeline = [
            {"$group": {"_id": "$customer", "orders": {"$sum": 1}, "revenue": {"$sum": "$price"}}},
            {"$sort": {"revenue": -1}},
        ]
        return [{"customer": x["_id"], "orders": x["orders"], "revenue": x["revenue"]}
                for x in self.sales.aggregate(pipeline) if x.get("_id")]
