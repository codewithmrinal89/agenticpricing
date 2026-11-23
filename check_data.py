"""Quick sanity check on data/pricing.db: row counts, lifecycle/category
breakdown, and the lowest-margin parts (the ones that should trip the
Decision Gate's exception flags)."""
from agents.db import get_connection

conn = get_connection()

(part_count,) = conn.execute("SELECT COUNT(*) FROM parts").fetchone()
print(f"Total parts: {part_count}\n")

print("By category:")
for row in conn.execute(
    "SELECT c.name, COUNT(*) AS n FROM parts p JOIN categories c ON c.id = p.category_id "
    "GROUP BY c.name ORDER BY n DESC"
):
    print(f"  {row['name']:<24} {row['n']}")

print("\nBy lifecycle status:")
for row in conn.execute(
    "SELECT ls.name, COUNT(*) AS n FROM parts p JOIN lifecycle_statuses ls ON ls.id = p.lifecycle_status_id "
    "GROUP BY ls.name ORDER BY n DESC"
):
    print(f"  {row['name']:<24} {row['n']}")

print(f"\n{'Part Number':<20} {'Category':<18} {'Lifecycle':<14} {'Cost':>12} {'List Price':>12} {'Margin %':>10}")
rows = conn.execute(
    """
    SELECT p.part_number, c.name AS category, ls.name AS lifecycle,
           co.actual_cost, ph.current_list_price,
           ROUND((ph.current_list_price - co.actual_cost) / ph.current_list_price * 100, 1) AS margin_pct
    FROM parts p
    JOIN categories c ON c.id = p.category_id
    JOIN lifecycle_statuses ls ON ls.id = p.lifecycle_status_id
    JOIN costs co ON co.part_number = p.part_number
    JOIN price_history ph ON ph.part_number = p.part_number
    ORDER BY margin_pct ASC
    LIMIT 15
    """
).fetchall()
for r in rows:
    print(f"{r['part_number']:<20} {r['category']:<18} {r['lifecycle']:<14} {r['actual_cost']:>12.2f} {r['current_list_price']:>12.2f} {r['margin_pct']:>9.1f}%")

conn.close()
